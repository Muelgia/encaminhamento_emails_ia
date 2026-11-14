import csv
from datetime import datetime
from loguru import logger
from src.models import ClassificationResult
from src.paths import CSV_FILE

COLUMNS = [
    "Data", "Remetente", "Copias", "Assunto", "Categoria",
    "Urgencia", "Resumo", "Justificativa", "Destino",
]


def _safe_cell(value) -> str:
    """
    Neutraliza injeção de fórmulas: o assunto/remetente vêm de terceiros e o
    CSV costuma ser aberto no Excel.
    """
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


class AuditService:
    """
    Gerencia a persistência de logs de auditoria em formato CSV.
    """
    def __init__(self):
        self.filepath = CSV_FILE
        self._ensure_storage()

    # =========================
    # Gestão de Persistência
    # =========================

    def _ensure_storage(self):
        if self.filepath.exists():
            try:
                with open(self.filepath, "r", encoding="utf-8-sig", newline="") as f:
                    header = next(csv.reader(f), [])
            except Exception:
                header = []
            if header == COLUMNS:
                return
            # Layout antigo/incompatível: preserva o arquivo e inicia um novo
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = self.filepath.with_name(f"{self.filepath.stem}_{stamp}.csv")
            self.filepath.rename(backup)
            logger.warning(f"Histórico com layout antigo preservado em: {backup.name}")

        # utf-8-sig no cabeçalho para o Excel reconhecer a acentuação
        with open(self.filepath, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerow(COLUMNS)

    def register(self, sender: str, cc: str, subject: str, res: ClassificationResult, destination: str):
        """
        Registra uma nova transação de e-mail no histórico de auditoria.
        """
        try:
            row = [
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                sender,
                cc,
                subject,
                res.category,
                res.urgency,
                res.summary,
                res.justification,
                destination or "NÃO ENCAMINHADO",
            ]
            with open(self.filepath, "a", encoding="utf-8", newline="") as f:
                csv.writer(f).writerow([_safe_cell(v) for v in row])

        except Exception as e:
            logger.error(f"Falha ao registrar auditoria em disco: {str(e)}")

# =========================
# Validação de Unidade (QA)
# =========================

if __name__ == "__main__":
    from src.utils import setup_logger
    setup_logger()

    logger.info("Iniciando teste de integridade do AuditService")
    audit = AuditService()

    res_teste = ClassificationResult(
        category="TESTE_MODULO",
        summary="Execução de teste unitário do módulo audit.",
        justification="Verificação de escrita em disco.",
        urgency=1
    )

    audit.register("tester@local", "copia@local", "Teste Unitário Audit", res_teste, "admin@local")

    with open(CSV_FILE, "r", encoding="utf-8-sig", newline="") as f:
        ultimo = list(csv.DictReader(f))[-1]

    if ultimo["Categoria"] == "TESTE_MODULO":
        logger.success("Teste de persistência concluído: Registro verificado.")
    else:
        logger.error("Divergência de dados detectada na leitura do CSV.")
