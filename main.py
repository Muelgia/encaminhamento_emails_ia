import argparse
import email
import re
import signal
import threading
from email.utils import parsedate_to_datetime, parseaddr
from datetime import datetime, timedelta
from loguru import logger

# =========================
# Importações de Módulos Internos
# =========================
from src.config_loader import (
    ConfigLoader, CUTOFF_DATE_STR, COOLDOWN_SECONDS, POLL_INTERVAL_SECONDS, MAX_FAILURES_PER_EMAIL,
    REQUIRE_KEYWORDS_TO_FORWARD, MARK_AS_SEEN,
)
from src.audit_service import AuditService
from src.email_service import EmailService
from src.ai_agent import AiAgent
from src.database import (
    Database, STATUS_ENCAMINHADO, STATUS_IGNORADO, STATUS_SEM_PALAVRA_CHAVE,
    STATUS_ABANDONADO, STATUS_ERRO, FINAL_STATUSES,
)
from src.models import ClassificationResult
from src.utils import decode_mime_header

# Meses em inglês fixos: o IMAP exige esse formato independentemente do locale do SO
IMAP_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MAX_STORED_BODY_CHARS = 100_000
MSG_ID_PATTERN = re.compile(r"<[^<>\s]+>")


class EmailProcessor:
    def __init__(self):
        # =========================
        # Inicialização de Componentes
        # =========================
        logger.info("Inicializando sistema de triagem...")
        self.config = ConfigLoader()
        self.audit = AuditService()
        self.db = Database()
        self.service = EmailService(self.config)
        self.agent = AiAgent(self.config)
        self.stop_event = threading.Event()
        # UIDs descartados nesta execução sem registro em banco (fora do período, do próprio robô)
        self.skipped_uids = set()

        self.date_cutoff = self._resolve_cutoff()
        logger.info(f"Lendo e-mails recebidos a partir de: {self.date_cutoff:%d/%m/%Y %H:%M:%S}")

    def _resolve_cutoff(self) -> datetime:
        if CUTOFF_DATE_STR.lower() != "agora":
            try:
                return datetime.strptime(CUTOFF_DATE_STR, "%d/%m/%Y %H:%M")
            except ValueError:
                logger.error(
                    f"CUTOFF_DATE inválida ('{CUTOFF_DATE_STR}'). Use 'agora' ou DD/MM/AAAA HH:MM. "
                    f"Assumindo 'agora'."
                )
        # Momento da primeira execução, salvo no banco: reinícios continuam de onde pararam
        return self.db.get_or_create_start()

    # =========================
    # Ciclo de Execução
    # =========================

    def run_forever(self):
        logger.info(f"Modo contínuo ativo: um ciclo a cada {POLL_INTERVAL_SECONDS}s.")
        while not self.stop_event.is_set():
            try:
                self.run()
            except Exception as e:
                logger.exception(f"Falha inesperada no ciclo: {str(e)}")
            self.stop_event.wait(POLL_INTERVAL_SECONDS)
        logger.info("Serviço encerrado.")

    def stop(self, *_):
        logger.info("Sinal de parada recebido. Encerrando após a etapa atual...")
        self.stop_event.set()

    def run(self):
        # =========================
        # Validação de Configurações
        # =========================
        if not self.config.flat_lookup:
            logger.error("Encerrando: Regras não carregadas.")
            return

        mail = self.service.connect_imap()
        if not mail:
            return

        try:
            # =========================
            # Busca e Filtragem Server-Side
            # =========================
            status, _ = mail.select("inbox")
            if status != "OK":
                logger.error("Não foi possível abrir a caixa de entrada.")
                return

            # UIDVALIDITY muda se o servidor renumerar a caixa: os UIDs antigos deixam de valer
            _, validity_data = mail.response("UIDVALIDITY")
            try:
                uidvalidity = int(validity_data[0])
            except (TypeError, ValueError, IndexError):
                uidvalidity = 0

            # SINCE só tem precisão de dia (e usa o fuso do servidor): busca com 1 dia
            # de folga e aplica o horário exato localmente.
            d = self.date_cutoff - timedelta(days=1)
            search_crit = f'(SINCE "{d.day:02d}-{IMAP_MONTHS[d.month - 1]}-{d.year}")'

            status, data = mail.uid("search", None, search_crit)
            all_uids = [int(u) for u in data[0].split()] if status == "OK" and data and data[0] else []

            # Lidos ou não: o controle do que já foi tratado é feito pelo banco
            done = self.db.finalized_uids(uidvalidity) | self.skipped_uids
            pending = [u for u in all_uids if u not in done]

            if not pending:
                logger.info("Nenhum e-mail pendente.")
                return

            logger.info(f"Processando {len(pending)} e-mails.")
            for idx, uid in enumerate(pending):
                if self.stop_event.is_set():
                    break
                self._process_one(mail, uid, uidvalidity, idx, len(pending))

        finally:
            try:
                mail.close()
            except Exception:
                pass
            try:
                mail.logout()
            except Exception:
                pass
            logger.info("Ciclo finalizado.")

    @staticmethod
    def _mark_seen(mail, uid):
        if MARK_AS_SEEN:
            mail.uid("store", str(uid), "+FLAGS", "(\\Seen)")

    @staticmethod
    def _parse_date(msg):
        """Data do e-mail convertida para o horário local (sem fuso), ou None."""
        raw = msg.get("Date")
        if not raw:
            return None
        try:
            parsed = parsedate_to_datetime(str(raw))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return parsed

    def _build_thread_context(self, thread_id, message_id) -> str:
        thread_summary, history = self.db.thread_context(thread_id, message_id)
        lines = [f"- [{h['data_email'] or 's/ data'}] {h['remetente']}: {h['resumo']}" for h in history]
        if thread_summary:
            lines.append(f"Resumo da conversa até aqui: {thread_summary}")
        return "\n".join(lines)

    def _process_one(self, mail, uid, uidvalidity, idx, total):
        # Injeção de contexto dinâmico para rastreabilidade
        with logger.contextualize(id=str(uid), progress=f"{idx+1}/{total}"):
            try:
                # =========================
                # Extração e Parsing
                # =========================
                # BODY.PEEK não marca como lido: isso só ocorre após o tratamento (ver _mark_seen)
                status, data = mail.uid("fetch", str(uid), "(BODY.PEEK[])")
                if status != "OK" or not data or not isinstance(data[0], tuple):
                    logger.warning("Mensagem indisponível no servidor. Ignorando.")
                    return
                msg = email.message_from_bytes(data[0][1])

                subject = decode_mime_header(msg.get("Subject")) or "(sem assunto)"
                sender = parseaddr(str(msg.get("From", "")))[1]
                to_str = decode_mime_header(msg.get("To"))
                cc_str = decode_mime_header(msg.get("Cc"))
                msg_date = self._parse_date(msg)

                message_id = str(msg.get("Message-ID") or "").strip()
                if not message_id:
                    # Sem Message-ID: chave estável derivada do UID
                    message_id = f"<uid-{uidvalidity}-{uid}@local>"

                # =========================
                # Validação de Regras de Negócio
                # =========================
                if sender.strip().lower() == self.service.my_email:
                    # Evita loop: mensagens enviadas pelo próprio robô
                    logger.info("Ignorando e-mail: Remetente é a própria conta do robô.")
                    self.skipped_uids.add(uid)
                    return

                if msg_date and msg_date < self.date_cutoff:
                    self.skipped_uids.add(uid)
                    return

                existing = self.db.get_email(message_id)
                if existing and existing["status"] in FINAL_STATUSES:
                    # Já tratado (ex.: e-mail movido/renumerado no servidor)
                    self.db.update_uid(message_id, uid, uidvalidity)
                    return

                clean_text, html_body = self.service.parse_email_content(msg)

                # Conversa (thread): agrupa respostas pelo encadeamento de Message-IDs
                references = MSG_ID_PATTERN.findall(
                    f"{msg.get('References') or ''} {msg.get('In-Reply-To') or ''}"
                )
                thread_id = existing["thread_id"] if existing else self.db.resolve_thread(message_id, references)

                record = {
                    "message_id": message_id, "uid": uid, "uidvalidity": uidvalidity,
                    "thread_id": thread_id, "remetente": sender, "destinatarios": to_str,
                    "copias": cc_str, "assunto": subject,
                    "data_email": msg_date.strftime("%Y-%m-%d %H:%M:%S") if msg_date else None,
                    "corpo": (clean_text or "")[:MAX_STORED_BODY_CHARS],
                }

                search_blob = (f"{subject} {clean_text} {sender}").lower()
                has_keywords = any(kw in search_blob for kw in self.config.all_keywords)

                # =========================
                # Processamento Inteligente
                # =========================
                logger.info(f"Resumindo e classificando | {sender} | {subject}")
                thread_context = self._build_thread_context(thread_id, message_id)
                res = self.agent.classify(subject, clean_text, sender, thread_context)

                if res is None:
                    self._handle_failure(mail, uid, record, "Falha na classificação por IA")
                    self.stop_event.wait(COOLDOWN_SECONDS)
                    return

                record.update({
                    "resumo": res.summary, "categoria": res.category,
                    "urgencia": res.urgency, "justificativa": res.justification,
                })
                dest = None

                if res.category == "IGNORAR":
                    record["status"] = STATUS_IGNORADO
                    logger.info(f"Processamento concluído: Categoria IGNORAR | {res.justification}")
                elif REQUIRE_KEYWORDS_TO_FORWARD and not has_keywords:
                    record["status"] = STATUS_SEM_PALAVRA_CHAVE
                    logger.info(f"Resumo salvo sem encaminhar: Ausência de palavras-chave | {sender}")
                else:
                    dest = self.service.forward_email(subject, clean_text, html_body, sender, res, msg)
                    if not dest:
                        self._handle_failure(
                            mail, uid, record, f"Falha no encaminhamento [{res.category}]"
                        )
                        self.stop_event.wait(COOLDOWN_SECONDS)
                        return
                    record["status"] = STATUS_ENCAMINHADO
                    record["destino"] = dest
                    logger.success(f"Concluído encaminhamento: [{res.category}] -> {dest}")

                self.db.save_email(record)
                self.db.update_thread(thread_id, subject, res.thread_summary or res.summary)
                self.audit.register(sender, cc_str, subject, res, dest)
                self._mark_seen(mail, uid)

                # Pausa entre chamadas de IA (interrompível no encerramento)
                self.stop_event.wait(COOLDOWN_SECONDS)

            except Exception as e:
                logger.exception(f"Falha no processamento do UID {uid}: {str(e)}")

    def _handle_failure(self, mail, uid, record, reason):
        """
        Falha técnica: o e-mail fica pendente para nova tentativa no próximo ciclo.
        Após o limite de falhas é abandonado (e registrado na auditoria).
        """
        attempts = self.db.save_email({**record, "status": STATUS_ERRO, "erro": reason}, failed=True)
        if attempts < MAX_FAILURES_PER_EMAIL:
            logger.warning(f"{reason} | Tentativa {attempts}/{MAX_FAILURES_PER_EMAIL}. Nova tentativa no próximo ciclo.")
            return

        logger.error(f"{reason} | Limite de {MAX_FAILURES_PER_EMAIL} falhas atingido. E-mail abandonado.")
        self.db.save_email({**record, "status": STATUS_ABANDONADO, "erro": reason})
        res = ClassificationResult(
            category=record.get("categoria") or "ERRO",
            summary=record.get("resumo") or "Falha técnica",
            justification=reason, urgency=record.get("urgencia") or 1,
        )
        self.audit.register(record["remetente"], record["copias"], record["assunto"], res, None)
        self._mark_seen(mail, uid)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Triagem e encaminhamento inteligente de e-mails.")
    parser.add_argument(
        "--loop", action="store_true",
        help="Executa continuamente, verificando a caixa a cada POLL_INTERVAL_SECONDS.",
    )
    args = parser.parse_args()

    try:
        processor = EmailProcessor()
    except RuntimeError as e:
        logger.critical(str(e))
        raise SystemExit(1)

    if args.loop:
        # Encerramento limpo no `docker compose stop` (SIGTERM) e no Ctrl+C
        signal.signal(signal.SIGTERM, processor.stop)
        signal.signal(signal.SIGINT, processor.stop)
        processor.run_forever()
    else:
        processor.run()
