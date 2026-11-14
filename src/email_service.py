import html
import imaplib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.utils import getaddresses, formataddr, formatdate, make_msgid
from typing import Tuple, Optional
from loguru import logger

from src.utils import TextSanitizer, decode_mime_header
from src.models import ClassificationResult
from src.config_loader import (
    ConfigLoader, ENV_IMAP_SERVER, ENV_IMAP_PORT, ENV_EMAIL_USER, ENV_EMAIL_PASS,
    ENV_SMTP_SERVER, ENV_SMTP_PORT, NETWORK_TIMEOUT_SECONDS,
)

class EmailService:
    def __init__(self, config: ConfigLoader):
        self.config = config
        self.creds = (ENV_IMAP_SERVER, ENV_EMAIL_USER, ENV_EMAIL_PASS, ENV_SMTP_SERVER)
        self.my_email = self.creds[1].strip().lower() if self.creds[1] else ""
        self.credentials_ok = all(self.creds)

        if not self.credentials_ok:
            logger.warning("Credenciais de ambiente incompletas detectadas (verifique config/.env).")

    # =========================
    # Conectividade e Protocolos
    # =========================

    def connect_imap(self):
        if not self.credentials_ok:
            logger.critical("Conexão IMAP abortada: credenciais ausentes em config/.env.")
            return None
        try:
            mail = imaplib.IMAP4_SSL(self.creds[0], ENV_IMAP_PORT, timeout=NETWORK_TIMEOUT_SECONDS)
            mail.login(self.creds[1], self.creds[2])
            return mail
        except Exception as e:
            logger.critical(f"Falha na conexão IMAP: {str(e)}")
            return None

    def connect_smtp(self):
        try:
            if ENV_SMTP_PORT == 465:
                server = smtplib.SMTP_SSL(self.creds[3], ENV_SMTP_PORT, timeout=NETWORK_TIMEOUT_SECONDS)
            else:
                server = smtplib.SMTP(self.creds[3], ENV_SMTP_PORT, timeout=NETWORK_TIMEOUT_SECONDS)
                server.starttls()
            server.login(self.creds[1], self.creds[2])
            return server
        except Exception as e:
            logger.error(f"Falha na conexão SMTP: {str(e)}")
            return None

    # =========================
    # Processamento de Conteúdo
    # =========================

    @staticmethod
    def _decode_part(part) -> Optional[str]:
        payload_bytes = part.get_payload(decode=True)
        if not payload_bytes:
            return None
        # Respeita o charset declarado; cai para utf-8/latin-1 se for inválido
        for charset in (part.get_content_charset(), "utf-8"):
            if not charset:
                continue
            try:
                return payload_bytes.decode(charset)
            except (LookupError, UnicodeDecodeError):
                continue
        return payload_bytes.decode("latin-1", errors="ignore")

    def parse_email_content(self, msg) -> Tuple[str, Optional[str]]:
        text_parts = []
        html_parts = []

        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            # Anexos (inclusive .txt/.html anexados) não fazem parte do corpo
            if "attachment" in str(part.get("Content-Disposition")).lower() or part.get_filename():
                continue
            ctype = part.get_content_type()
            if ctype not in ("text/plain", "text/html"):
                continue
            try:
                payload = self._decode_part(part)
            except Exception:
                continue
            if not payload:
                continue
            (html_parts if ctype == "text/html" else text_parts).append(payload)

        raw_text = "\n".join(text_parts)
        html_content = "\n".join(html_parts) if html_parts else None

        text_for_ai = ""
        if html_content:
            text_for_ai = TextSanitizer.clean_html_to_text(html_content)
        # HTML só com imagens/vazio: usa a versão em texto puro
        if not text_for_ai.strip() and raw_text:
            text_for_ai = raw_text

        return text_for_ai, html_content

    # =========================
    # Lógica de Encaminhamento
    # =========================

    def _build_smart_reply_to(self, original_msg) -> Tuple[str, str]:
        """
        Retorna (valor do cabeçalho Reply-To, versão legível para exibição).
        """
        reply_to_field = original_msg.get_all('Reply-To', [])
        from_field = original_msg.get_all('From', [])
        sender_source = reply_to_field if reply_to_field else from_field

        to_field = original_msg.get_all('To', [])
        cc_field = original_msg.get_all('Cc', [])
        all_raw_addrs = [str(v) for v in (sender_source + to_field + cc_field)]

        header_items = []
        display_items = []
        seen = set()

        for name, addr in getaddresses(all_raw_addrs):
            clean_addr = addr.strip().lower()
            if not clean_addr or "@" not in clean_addr or clean_addr in seen or clean_addr == self.my_email:
                continue
            seen.add(clean_addr)
            name = decode_mime_header(name)
            # formataddr trata aspas e codifica nomes acentuados (RFC 2047)
            header_items.append(formataddr((name, addr.strip())))
            display_items.append(f"{name} <{addr.strip()}>" if name else addr.strip())

        return ", ".join(header_items), ", ".join(display_items)

    def forward_email(self, subject, body_clean, body_html, sender, res: ClassificationResult, original_msg):
        """
        Encaminha o e-mail ao destino da categoria. Retorna o destino em caso de
        sucesso ou None quando nada foi enviado.
        """
        if res.category == "IGNORAR":
            return None

        target = self.config.get_target_email(res.category)
        if not target:
            logger.warning(f"Destinatário não encontrado para categoria: {res.category}")
            return None

        msg = MIMEMultipart('mixed')
        msg['From'] = self.creds[1]
        msg['To'] = target
        msg['Subject'] = f"[{res.category}] {decode_mime_header(subject)}"
        msg['Date'] = formatdate(localtime=True)
        msg['Message-ID'] = make_msgid()

        reply_to_header, reply_to_display = self._build_smart_reply_to(original_msg)
        if reply_to_header:
            msg['Reply-To'] = reply_to_header

        # =========================
        # Templates de Mensagem (UI)
        # =========================

        # Conteúdo vindo da IA/terceiros é sempre escapado antes de entrar no HTML
        esc_category = html.escape(res.category)
        esc_summary = html.escape(res.summary)
        esc_justification = html.escape(res.justification)
        esc_reply_to = html.escape(reply_to_display or sender or "")

        # Cor e rótulo acompanham o nível de urgência (1-5)
        urgency_label, urgency_color, urgency_bg = {
            1: ("Baixa", "#15803d", "#dcfce7"),
            2: ("Baixa", "#15803d", "#dcfce7"),
            3: ("Média", "#b45309", "#fef3c7"),
            4: ("Alta", "#c2410c", "#ffedd5"),
            5: ("Crítica", "#b91c1c", "#fee2e2"),
        }.get(res.urgency, ("Baixa", "#15803d", "#dcfce7"))

        urgency_meter = "".join(
            f'<td style="width: 22px; height: 6px; font-size: 0; line-height: 0; '
            f'background-color: {urgency_color if level <= res.urgency else "#e2e8f0"};">&nbsp;</td>'
            f'<td style="width: 3px; font-size: 0; line-height: 0;">&nbsp;</td>'
            for level in range(1, 6)
        )

        label_style = (
            "margin: 0 0 6px 0; font-size: 11px; font-weight: 700; color: #64748b; "
            "text-transform: uppercase; letter-spacing: 0.8px;"
        )

        # Contexto da conversa só aparece quando acrescenta algo ao resumo do e-mail
        thread_summary = (res.thread_summary or "").strip()
        thread_block = ""
        if thread_summary and thread_summary != res.summary.strip():
            thread_block = f"""
                        <tr><td style="padding: 0 24px 20px 24px;">
                            <p style="{label_style}">Contexto da conversa</p>
                            <p style="margin: 0; font-size: 14px; line-height: 1.55; color: #475569;">{html.escape(thread_summary)}</p>
                        </td></tr>"""

        # Layout em tabelas + estilos inline: único formato que Outlook e Gmail renderizam igual
        html_header = f"""
        <div style="display: none; max-height: 0; overflow: hidden; opacity: 0; font-size: 1px; line-height: 1px; color: #f1f5f9;">{esc_summary}</div>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color: #f1f5f9; font-family: 'Segoe UI', 'Helvetica Neue', Helvetica, Arial, sans-serif;">
            <tr><td align="center" style="padding: 24px 12px 8px 12px;">
                <table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0" style="width: 100%; max-width: 600px; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; border-collapse: separate; overflow: hidden;">
                    <tr><td style="background-color: #0f172a; padding: 14px 24px;">
                        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                            <tr>
                                <td style="color: #cbd5e1; font-size: 12px; font-weight: 600; letter-spacing: 1px; text-transform: uppercase;">Robô de Triagem</td>
                                <td align="right">
                                    <span style="display: inline-block; background-color: #2563eb; color: #ffffff; padding: 5px 12px; border-radius: 4px; font-size: 12px; font-weight: 700; letter-spacing: 0.5px;">{esc_category}</span>
                                </td>
                            </tr>
                        </table>
                    </td></tr>
                    <tr><td style="background-color: {urgency_bg}; padding: 10px 24px; border-bottom: 1px solid #e2e8f0;">
                        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                            <tr>
                                <td style="font-size: 13px; color: {urgency_color};">Urgência <strong>{urgency_label}</strong> &middot; {res.urgency}/5</td>
                                <td align="right">
                                    <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>{urgency_meter}</tr></table>
                                </td>
                            </tr>
                        </table>
                    </td></tr>
                    <tr><td style="padding: 22px 24px 20px 24px;">
                        <p style="{label_style}">Resumo</p>
                        <p style="margin: 0; font-size: 16px; line-height: 1.55; color: #0f172a;">{esc_summary}</p>
                    </td></tr>{thread_block}
                    <tr><td style="padding: 0 24px 24px 24px;">
                        <p style="{label_style}">Por que chegou até você</p>
                        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                            <tr><td style="border-left: 3px solid #cbd5e1; background-color: #f8fafc; padding: 10px 14px; font-size: 13px; line-height: 1.5; color: #475569;">{esc_justification}</td></tr>
                        </table>
                    </td></tr>
                    <tr><td style="background-color: #fffbeb; border-top: 1px solid #fde68a; padding: 14px 24px; font-size: 13px; line-height: 1.5; color: #92400e;">
                        Ao clicar em <strong>Responder</strong>, sua mensagem será enviada para:
                        <div style="margin-top: 4px; font-family: Consolas, 'Courier New', monospace; font-size: 13px; color: #78350f; word-break: break-all;">{esc_reply_to}</div>
                    </td></tr>
                </table>
            </td></tr>
            <tr><td align="center" style="padding: 8px 12px 16px 12px; font-size: 11px; color: #94a3b8; letter-spacing: 1px; text-transform: uppercase;">Mensagem original &darr;</td></tr>
        </table>
        """

        text_header = (
            f"=== ROBÔ DE TRIAGEM ===\n"
            f"CATEGORIA: {res.category}\n"
            f"URGÊNCIA: {res.urgency}/5\n"
            f"RESUMO: {res.summary}\n"
            f"JUSTIFICATIVA: {res.justification}\n"
            f"\n[!] ALERTA: Responder enviará para: {reply_to_display}\n"
            f"=======================\n\n"
        )

        alt_container = MIMEMultipart('alternative')
        full_text = text_header + (body_clean if body_clean else "Ver conteúdo HTML.")
        alt_container.attach(MIMEText(full_text, 'plain', 'utf-8'))

        # E-mails só em texto também recebem o card visual
        original_html = body_html or (
            f'<pre style="white-space: pre-wrap; font-family: inherit;">{html.escape(body_clean or "")}</pre>'
        )
        alt_container.attach(MIMEText(html_header + original_html, 'html', 'utf-8'))

        msg.attach(alt_container)
        self._attach_original_files(msg, original_msg)

        server = self.connect_smtp()
        if not server:
            return None
        try:
            recipients = [addr.strip() for addr in target.split(",") if addr.strip()]
            server.sendmail(self.creds[1], recipients, msg.as_string())
            return target
        except Exception as e:
            logger.error(f"Erro ao enviar e-mail via SMTP: {str(e)}")
            return None
        finally:
            try:
                server.quit()
            except Exception:
                pass

    def _attach_original_files(self, msg_container, original_msg):
        if not original_msg:
            return
        for part in original_msg.walk():
            if part.get_content_maintype() == 'multipart':
                continue

            disposition = str(part.get("Content-Disposition")).lower()
            filename = decode_mime_header(part.get_filename())
            content_id = part.get("Content-ID")
            is_inline_image = bool(content_id) and part.get_content_maintype() == "image"

            if not (filename or "attachment" in disposition or is_inline_image):
                continue
            if part.get_content_type() in ["text/plain", "text/html"] and not filename:
                continue
            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                anexo = MIMEBase(part.get_content_maintype(), part.get_content_subtype())
                anexo.set_payload(payload)
                encoders.encode_base64(anexo)
                safe_filename = filename or "anexo_desconhecido"
                # Forma em tupla: nomes acentuados são codificados via RFC 2231
                anexo.add_header(
                    'Content-Disposition',
                    'inline' if is_inline_image and "attachment" not in disposition else 'attachment',
                    filename=('utf-8', '', safe_filename),
                )
                if content_id:
                    # Mantém imagens embutidas (cid:) funcionando no corpo HTML
                    anexo.add_header('Content-ID', content_id)
                msg_container.attach(anexo)
            except Exception:
                logger.warning(f"Falha ao anexar arquivo: {filename}")
