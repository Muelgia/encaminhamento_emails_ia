import sys
import re
from email.header import decode_header, make_header
from bs4 import BeautifulSoup
from loguru import logger
from src.paths import LOG_FILE

# =========================
# Configuração de Telemetria
# =========================

def setup_logger():
    """
    Configura o motor de logs com padrão de mercado.
    Inclui data, nível, origem (módulo:linha), contexto do e-mail e mensagem.
    """
    logger.remove()
    # Valores padrão do contexto, sobrescritos via logger.contextualize()
    logger.configure(extra={"id": "-", "progress": "-"})

    # Log em arquivo (Persistência)
    logger.add(
        LOG_FILE,
        rotation="10 MB",
        retention="10 days",
        level="INFO",
        encoding="utf-8",
        # Padrão de mercado: Data Hora | Nível | Origem (Módulo:Linha) | Contexto | Mensagem
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} | id={extra[id]} {extra[progress]} | {message}"
    )

    # Log em console (Monitoramento)
    logger.add(
        sys.stderr,
        level="INFO",
        # Formato visual com destaque para a origem do log
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <magenta>{name}:{line}</magenta> | <yellow>{extra[progress]}</yellow> | <cyan>{message}</cyan>"
    )

    return logger

# =========================
# Sanitização e Processamento
# =========================

def decode_mime_header(value) -> str:
    """
    Decodifica cabeçalhos RFC 2047 (ex.: '=?UTF-8?B?...?=') em texto de linha única.
    """
    if not value:
        return ""
    try:
        text = str(make_header(decode_header(str(value))))
    except Exception:
        text = str(value)
    # Remove quebras de linha/dobras: evita injeção de cabeçalhos no reenvio
    return " ".join(text.split())


class TextSanitizer:
    """
    Ferramentas para normalização de conteúdo e limpeza de HTML.
    """
    @staticmethod
    def clean_html_to_text(html_content: str) -> str:
        if not html_content:
            return ""

        try:
            soup = BeautifulSoup(html_content, 'html.parser')

            # Extração de elementos ruidosos
            for element in soup(["script", "style", "head", "title", "meta", "noscript"]):
                element.extract()

            text = soup.get_text(separator='\n', strip=True)
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            return "\n".join(lines)

        except Exception:
            # Fallback seguro via Regex em caso de falha no parser
            text = re.sub(r'<[^>]+>', ' ', html_content)
            return " ".join(text.split())

# =========================
# Validação de Unidade (QA)
# =========================

if __name__ == "__main__":
    setup_logger()

    logger.info("Iniciando validação de sanitização")

    html_exemplo = """
    <html>
        <head><title>Ignorar</title></head>
        <style>.css { color: red; }</style>
        <body>
            <h1>Olá Mundo</h1>
            <p>Este é um <b>teste</b>.</p>
            <script>console.log('hack');</script>
            <br>
            <p>Fim.</p>
    """

    resultado = TextSanitizer.clean_html_to_text(html_exemplo)
    logger.info(f"Resultado processado:\n{resultado}")

    assert decode_mime_header("=?UTF-8?B?T2zDoSBNdW5kbw==?=") == "Olá Mundo"
    assert decode_mime_header(None) == ""
    logger.success("Decodificação de cabeçalhos validada.")
