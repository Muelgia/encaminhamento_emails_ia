import email
from time import sleep
from email.utils import parsedate_to_datetime, parseaddr
from datetime import datetime
from loguru import logger

# =========================
# Importações de Módulos Internos
# =========================
from src.config_loader import ConfigLoader, CUTOFF_DATE_STR, COOLDOWN_SECONDS
from src.audit_service import AuditService
from src.email_service import EmailService
from src.ai_agent import AiAgent

class EmailProcessor:
    def __init__(self):
        # Injeção de contexto global para execução local
        logger.configure(extra={"user": "machine"})
        
        # =========================
        # Inicialização de Componentes
        # =========================
        logger.info("Inicializando sistema de triagem...")
        self.config = ConfigLoader()
        self.audit = AuditService()
        self.service = EmailService(self.config)
        self.agent = AiAgent(self.config)
        
        self.date_cutoff = None
        if CUTOFF_DATE_STR:
            try:
                self.date_cutoff = datetime.strptime(CUTOFF_DATE_STR, "%d/%m/%Y %H:%M")
                logger.info(f"Filtro de data ativo: {self.date_cutoff}")
            except Exception: 
                logger.error("Data de corte configurada inválida.")

    def run(self):
        # =========================
        # Validação de Configurações
        # =========================
        if not self.config.raw_data:
            logger.error("Encerrando: Regras não carregadas.")
            return
        
        mail = self.service.connect_imap()
        if not mail: 
            return

        try:
            # =========================
            # Busca e Filtragem Server-Side
            # =========================
            mail.select("inbox")
            
            search_crit = '(UNSEEN)'
            if self.date_cutoff:
                imap_date = self.date_cutoff.strftime("%d-%b-%Y")
                search_crit = f'(SINCE "{imap_date}" UNSEEN)'
            
            logger.info(f"Buscando e-mails: {search_crit}")
            _, data = mail.search(None, search_crit)
            email_ids = data[0].split()
            
            if not email_ids:
                logger.info("Nenhum e-mail pendente.")
                return

            logger.info(f"Processando {len(email_ids)} e-mails.")
            for idx, e_id in enumerate(email_ids):
                self._process_one(mail, e_id, idx, len(email_ids))
                
        finally:
            try:
                mail.close()
                mail.logout()
            except Exception: 
                pass
            logger.info("Ciclo finalizado.")

    def _process_one(self, mail, email_id, idx, total):
        # Injeção de contexto dinâmico para rastreabilidade
        with logger.contextualize(user="machine", id=email_id.decode(), progress=f"{idx+1}/{total}"):
            try:
                # =========================
                # Extração e Parsing
                # =========================
                _, data = mail.fetch(email_id, "(RFC822)")
                msg = email.message_from_bytes(data[0][1])
                
                subj_raw = msg["Subject"]
                subject = str(email.header.decode_header(subj_raw)[0][0])
                if isinstance(subject, bytes): 
                    subject = subject.decode('utf-8', 'ignore')
                
                sender = parseaddr(msg.get("From"))[1]

                # Extração de Cópias (Cc)
                cc_raw = msg.get("Cc")
                cc_str = str(cc_raw).replace("\n", " ") if cc_raw else ""
                
                # =========================
                # Validação de Regras de Negócio
                # =========================
                if self.date_cutoff:
                    msg_date_str = msg.get("Date")
                    if msg_date_str:
                        msg_date = parsedate_to_datetime(msg_date_str).replace(tzinfo=None)
                        if msg_date < self.date_cutoff:
                            logger.info(f"Ignorando e-mail: Data antiga | {sender}")
                            return

                clean_text, html_body = self.service.parse_email_content(msg)
                
                search_blob = (f"{subject} {clean_text} {sender}").lower()
                if not any(kw in search_blob for kw in self.config.all_keywords):
                    logger.info(f"Ignorando e-mail: Ausência de palavras-chave | {sender}")
                    return

                # =========================
                # Processamento Inteligente
                # =========================
                logger.info(f"Iniciando classificação IA | {sender}")
                res = self.agent.classify(subject, clean_text, sender)

                dest = self.service.forward_email(subject, clean_text, html_body, sender, res, msg)
                self.audit.register(sender, cc_str, subject, res, dest)

                if res.category == "IGNORAR":
                    logger.info(f"Processamento concluído: Categoria IGNORAR | {res.justification}")
                else:
                    logger.success(f"Concluído encaminhamento: [{res.category}] -> {dest}")

                sleep(COOLDOWN_SECONDS)

            except Exception as e:
                logger.exception(f"Falha no processamento do ID {email_id}: {str(e)}")

if __name__ == "__main__":
    # Início da execução do serviço
    EmailProcessor().run()