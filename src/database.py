import sqlite3
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from loguru import logger
from src.paths import DB_FILE

# Status em que o e-mail não precisa mais ser reprocessado
STATUS_ENCAMINHADO = "ENCAMINHADO"
STATUS_IGNORADO = "IGNORADO"
STATUS_SEM_PALAVRA_CHAVE = "SEM_PALAVRA_CHAVE"
STATUS_ABANDONADO = "ABANDONADO"
# Falha técnica: será tentado de novo no próximo ciclo
STATUS_ERRO = "ERRO"

FINAL_STATUSES = (STATUS_ENCAMINHADO, STATUS_IGNORADO, STATUS_SEM_PALAVRA_CHAVE, STATUS_ABANDONADO)

SCHEMA = """
CREATE TABLE IF NOT EXISTS emails (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id    TEXT NOT NULL UNIQUE,
    uid           INTEGER,
    uidvalidity   INTEGER,
    thread_id     TEXT NOT NULL,
    remetente     TEXT,
    destinatarios TEXT,
    copias        TEXT,
    assunto       TEXT,
    data_email    TEXT,
    corpo         TEXT,
    resumo        TEXT,
    categoria     TEXT,
    urgencia      INTEGER,
    justificativa TEXT,
    destino       TEXT,
    status        TEXT NOT NULL,
    tentativas    INTEGER NOT NULL DEFAULT 0,
    erro          TEXT,
    criado_em     TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_emails_thread ON emails(thread_id);
CREATE INDEX IF NOT EXISTS idx_emails_uid ON emails(uidvalidity, uid);

CREATE TABLE IF NOT EXISTS conversas (
    thread_id     TEXT PRIMARY KEY,
    assunto       TEXT,
    resumo        TEXT,
    participantes TEXT,
    total_emails  INTEGER NOT NULL DEFAULT 0,
    atualizado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS estado (
    chave TEXT PRIMARY KEY,
    valor TEXT
);
"""

EMAIL_FIELDS = (
    "message_id", "uid", "uidvalidity", "thread_id", "remetente", "destinatarios", "copias",
    "assunto", "data_email", "corpo", "resumo", "categoria", "urgencia", "justificativa",
    "destino", "status", "erro",
)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Database:
    """
    Banco local (SQLite) com todos os e-mails lidos, seus resumos e as conversas.
    Arquivo único em data/emails.db: não exige servidor de banco de dados.
    """
    def __init__(self, path=DB_FILE):
        self.path = path
        self.conn = sqlite3.connect(str(path), timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # =========================
    # Estado do Serviço
    # =========================

    def get_state(self, key: str) -> Optional[str]:
        row = self.conn.execute("SELECT valor FROM estado WHERE chave = ?", (key,)).fetchone()
        return row["valor"] if row else None

    def set_state(self, key: str, value: str):
        self.conn.execute(
            "INSERT INTO estado (chave, valor) VALUES (?, ?) "
            "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
            (key, value),
        )
        self.conn.commit()

    def get_or_create_start(self) -> datetime:
        """
        Momento da primeira execução. Persistido para que reinícios do serviço
        não pulem e-mails recebidos enquanto ele esteve parado.
        """
        saved = self.get_state("inicio_monitoramento")
        if saved:
            try:
                return datetime.fromisoformat(saved)
            except ValueError:
                logger.warning("Marco de início inválido no banco. Recriando.")
        start = datetime.now().replace(microsecond=0)
        self.set_state("inicio_monitoramento", start.isoformat())
        return start

    # =========================
    # E-mails
    # =========================

    def finalized_uids(self, uidvalidity: int) -> Set[int]:
        marks = ",".join("?" * len(FINAL_STATUSES))
        rows = self.conn.execute(
            f"SELECT uid FROM emails WHERE uidvalidity = ? AND uid IS NOT NULL AND status IN ({marks})",
            (uidvalidity, *FINAL_STATUSES),
        ).fetchall()
        return {row["uid"] for row in rows}

    def get_email(self, message_id: str) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM emails WHERE message_id = ?", (message_id,)).fetchone()

    def update_uid(self, message_id: str, uid: int, uidvalidity: int):
        self.conn.execute(
            "UPDATE emails SET uid = ?, uidvalidity = ? WHERE message_id = ?",
            (uid, uidvalidity, message_id),
        )
        self.conn.commit()

    def save_email(self, data: Dict, failed: bool = False) -> int:
        """
        Insere ou atualiza o e-mail (chave: message_id). Retorna o total de
        tentativas com falha acumuladas.
        """
        now = _now()
        values = {field: data.get(field) for field in EMAIL_FIELDS}
        columns = ", ".join(EMAIL_FIELDS)
        placeholders = ", ".join(f":{f}" for f in EMAIL_FIELDS)
        updates = ", ".join(f"{f} = excluded.{f}" for f in EMAIL_FIELDS if f != "message_id")
        self.conn.execute(
            f"INSERT INTO emails ({columns}, tentativas, criado_em, atualizado_em) "
            f"VALUES ({placeholders}, :inc, :now, :now) "
            f"ON CONFLICT(message_id) DO UPDATE SET {updates}, "
            f"tentativas = emails.tentativas + :inc, atualizado_em = :now",
            {**values, "inc": 1 if failed else 0, "now": now},
        )
        self.conn.commit()
        row = self.get_email(values["message_id"])
        return row["tentativas"] if row else 0

    # =========================
    # Conversas (threads)
    # =========================

    def resolve_thread(self, message_id: str, references: List[str]) -> str:
        """
        Identifica a conversa a partir dos cabeçalhos References/In-Reply-To.
        """
        if references:
            marks = ",".join("?" * len(references))
            row = self.conn.execute(
                f"SELECT thread_id FROM emails WHERE message_id IN ({marks}) "
                f"OR thread_id IN ({marks}) LIMIT 1",
                (*references, *references),
            ).fetchone()
            if row:
                return row["thread_id"]
            # Conversa iniciada antes do monitoramento: a raiz é a 1ª referência
            return references[0]
        return message_id

    def thread_context(self, thread_id: str, exclude_message_id: str, limit: int = 5) -> Tuple[str, List[sqlite3.Row]]:
        """
        Retorna (resumo consolidado da conversa, últimos e-mails já resumidos).
        """
        conv = self.conn.execute("SELECT resumo FROM conversas WHERE thread_id = ?", (thread_id,)).fetchone()
        rows = self.conn.execute(
            "SELECT remetente, data_email, resumo FROM emails "
            "WHERE thread_id = ? AND message_id != ? AND resumo IS NOT NULL AND resumo != '' "
            "ORDER BY COALESCE(data_email, criado_em) DESC LIMIT ?",
            (thread_id, exclude_message_id, limit),
        ).fetchall()
        return (conv["resumo"] if conv and conv["resumo"] else ""), list(reversed(rows))

    def update_thread(self, thread_id: str, subject: str, summary: str):
        stats = self.conn.execute(
            "SELECT COUNT(*) AS total, GROUP_CONCAT(DISTINCT remetente) AS participantes "
            "FROM emails WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        self.conn.execute(
            "INSERT INTO conversas (thread_id, assunto, resumo, participantes, total_emails, atualizado_em) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(thread_id) DO UPDATE SET resumo = excluded.resumo, "
            "participantes = excluded.participantes, total_emails = excluded.total_emails, "
            "atualizado_em = excluded.atualizado_em",
            (thread_id, subject, summary, stats["participantes"], stats["total"], _now()),
        )
        self.conn.commit()

# =========================
# Consulta Rápida (python -m src.database)
# =========================

if __name__ == "__main__":
    db = Database()
    print(f"Banco: {db.path}")
    print(f"Monitorando desde: {db.get_state('inicio_monitoramento') or '(ainda não iniciado)'}")

    print("\n--- Últimos e-mails ---")
    for r in db.conn.execute(
        "SELECT id, data_email, remetente, assunto, categoria, status, resumo "
        "FROM emails ORDER BY id DESC LIMIT 20"
    ):
        print(f"#{r['id']} | {r['data_email']} | {r['remetente']} | [{r['status']}/{r['categoria']}] {r['assunto']}")
        print(f"     {r['resumo']}")

    print("\n--- Conversas ---")
    for r in db.conn.execute(
        "SELECT assunto, total_emails, resumo FROM conversas ORDER BY atualizado_em DESC LIMIT 10"
    ):
        print(f"({r['total_emails']} e-mails) {r['assunto']}\n     {r['resumo']}")
