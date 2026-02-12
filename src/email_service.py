import sys
import os
import imaplib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.utils import parseaddr, getaddresses
from typing import Tuple, Optional
from loguru import logger

# =========================
# Ajuste de Ambiente e Imports
# =========================
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils import TextSanitizer
from src.models import ClassificationResult
from src.config_loader import ConfigLoader, ENV_IMAP_SERVER, ENV_EMAIL_USER, ENV_EMAIL_PASS, ENV_SMTP_SERVER

class EmailService:
    def __init__(self, config: ConfigLoader):
        self.config = config
        self.creds = (ENV_IMAP_SERVER, ENV_EMAIL_USER, ENV_EMAIL_PASS, ENV_SMTP_SERVER)
        self.my_email = self.creds[1].strip().lower() if self.creds[1] else ""
        
        if not all(self.creds):
            logger.warning("Credenciais de ambiente incompletas detectadas.")

    # =========================
    # Conectividade e Protocolos
    # =========================

    def connect_imap(self):
        try:
            mail = imaplib.IMAP4_SSL(self.creds[0])
            mail.login(self.creds[1], self.creds[2])
            return mail
        except Exception as e:
            logger.critical(f"Falha na conexão IMAP: {str(e)}")
            return None

    def connect_smtp(self):
        try:
            server = smtplib.SMTP(self.creds[3], 587)
            server.starttls()
            server.login(self.creds[1], self.creds[2])
            return server
        except Exception as e:
            logger.error(f"Falha na conexão SMTP: {str(e)}")
            return None

    # =========================
    # Processamento de Conteúdo
    # =========================

    def parse_email_content(self, msg) -> Tuple[str, Optional[str]]:
        raw_text = ""
        html_content = None

        def decode_block(blob):
            try:
                return blob.decode('utf-8')
            except Exception:
                return blob.decode('latin-1', errors='ignore')

        if msg.is_multipart():
            for part in msg.walk():
                if "attachment" in str(part.get("Content-Disposition")):
                    continue
                try:
                    payload_bytes = part.get_payload(decode=True)
                    if not payload_bytes:
                        continue
                    payload = decode_block(payload_bytes)
                    ctype = part.get_content_type()
                    if ctype == "text/html":
                        html_content = payload
                    elif ctype == "text/plain":
                        raw_text += payload
                except Exception:
                    continue
        else:
            try:
                payload_bytes = msg.get_payload(decode=True)
                if payload_bytes:
                    payload = decode_block(payload_bytes)
                    if msg.get_content_type() == "text/html":
                        html_content = payload
                    else:
                        raw_text = payload
            except Exception:
                pass

        text_for_ai = ""
        if html_content:
            text_for_ai = TextSanitizer.clean_html_to_text(html_content)
        elif raw_text:
            text_for_ai = raw_text

        return text_for_ai, html_content

    # =========================
    # Lógica de Encaminhamento
    # =========================

    def _build_smart_reply_to(self, original_msg) -> str:
        reply_to_field = original_msg.get_all('Reply-To', [])
        from_field = original_msg.get_all('From', [])
        sender_source = reply_to_field if reply_to_field else from_field
        
        to_field = original_msg.get_all('To', [])
        cc_field = original_msg.get_all('Cc', [])
        all_raw_addrs = sender_source + to_field + cc_field
        
        parsed_addrs = getaddresses(all_raw_addrs)
        unique_emails = []
        seen = set()

        for name, addr in parsed_addrs:
            clean_addr = addr.strip().lower()
            if clean_addr and (clean_addr not in seen) and (clean_addr != self.my_email):
                formatted = f'"{name}" <{addr}>' if name else addr
                unique_emails.append(formatted)
                seen.add(clean_addr)

        return ", ".join(unique_emails)

    def forward_email(self, subject, body_clean, body_html, sender, res: ClassificationResult, original_msg):
        if res.category == "IGNORAR":
            return None
        
        target = self.config.get_target_email(res.category)
        if not target:
            logger.warning(f"Destinatário não encontrado para categoria: {res.category}")
            return None

        msg = MIMEMultipart('mixed')
        msg['From'] = self.creds[1]
        msg['To'] = target
        msg['Subject'] = f"[{res.category}] {subject}"

        reply_to_header = self._build_smart_reply_to(original_msg)
        if reply_to_header:
            msg['Reply-To'] = reply_to_header

        # =========================
        # Templates de Mensagem (UI)
        # =========================

        html_header = f"""
        <div style="background-color: #f8fafc; padding: 20px 0; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #334155;">
            <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 8px; border: 1px solid #e2e8f0; overflow: hidden;">
                <div style="background-color: #0f172a; padding: 16px 24px; display: flex; align-items: center; justify-content: space-between;">
                    <span style="color: #ffffff; font-weight: 600; font-size: 14px; letter-spacing: 0.5px;">ROBÔ DE TRIAGEM</span>
                    <span style="background-color: #3b82f6; color: #ffffff; padding: 4px 12px; border-radius: 99px; font-size: 12px; font-weight: 700;">{res.category}</span>
                </div>
                <div style="padding: 24px;">
                    <div style="margin-bottom: 20px;">
                        <p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px;">RESUMO</p>
                        <p style="margin: 0; font-size: 15px; line-height: 1.5; color: #1e293b;">{res.summary}</p>
                    </div>
                    <div>
                        <p style="margin: 0 0 6px 0; font-size: 11px; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px;">JUSTIFICATIVA</p>
                        <div style="background-color: #f1f5f9; padding: 10px 12px; border-radius: 6px; font-size: 13px; color: #475569;">{res.justification}</div>
                    </div>
                </div>
                <div style="background-color: #fff7ed; padding: 16px 24px; border-top: 1px solid #fed7aa; font-size: 13px; color: #9a3412; line-height: 1.5;">
                    <strong>⚠️ Atenção:</strong> Ao clicar em <u>Responder</u>, sua mensagem será enviada para:<br>
                    <span style="color: #c2410c; font-family: monospace; display: block; margin-top: 4px; word-break: break-all;">{reply_to_header}</span>
                </div>
            </div>
            <div style="text-align: center; margin-top: 20px; font-size: 12px; color: #94a3b8;">Mensagem original abaixo &darr;</div>
        </div>
        """
        
        text_header = (
            f"=== ROBÔ DE TRIAGEM ===\n"
            f"CATEGORIA: {res.category}\n"
            f"RESUMO: {res.summary}\n"
            f"JUSTIFICATIVA: {res.justification}\n"
            f"\n[!] ALERTA: Responder enviará para: {reply_to_header}\n"
            f"=======================\n\n"
        )

        alt_container = MIMEMultipart('alternative')
        full_text = text_header + (body_clean if body_clean else "Ver conteúdo HTML.")
        alt_container.attach(MIMEText(full_text, 'plain', 'utf-8'))
        
        if body_html:
            full_html = html_header + body_html
            alt_container.attach(MIMEText(full_html, 'html', 'utf-8'))
        
        msg.attach(alt_container)
        self._attach_original_files(msg, original_msg)

        server = self.connect_smtp()
        if server:
            try:
                server.sendmail(self.creds[1], target, msg.as_string())
                server.quit()
                return target
            except Exception as e:
                logger.error(f"Erro ao enviar e-mail via SMTP: {str(e)}")
        return None

    def _attach_original_files(self, msg_container, original_msg):
        if not original_msg:
            return
        for part in original_msg.walk():
            if part.get_content_maintype() == 'multipart':
                continue
            
            disposition = str(part.get("Content-Disposition"))
            filename = part.get_filename()
            
            if filename or "attachment" in disposition:
                if part.get_content_type() in ["text/plain", "text/html"] and not filename:
                    continue
                try:
                    anexo = MIMEBase(part.get_content_maintype(), part.get_content_subtype())
                    anexo.set_payload(part.get_payload(decode=True))
                    encoders.encode_base64(anexo)
                    safe_filename = filename if filename else "anexo_desconhecido"
                    anexo.add_header('Content-Disposition', f'attachment; filename="{safe_filename}"')
                    msg_container.attach(anexo)
                except Exception:
                    logger.warning(f"Falha ao anexar arquivo: {filename}")

# =========================
# Validação de Unidade (QA)
# =========================
if __name__ == "__main__":
    logger.info("Módulo EmailService carregado com template otimizado.")