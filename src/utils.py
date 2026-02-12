import sys
import re
from bs4 import BeautifulSoup
from loguru import logger
from src.paths import LOG_FILE

# =========================
# Configuração de Telemetria
# =========================

def setup_logger():
    """
    Configura o motor de logs com padrão de mercado.
    Inclui data, nível, origem (módulo:linha) e mensagem.
    """
    logger.remove()
    
    # Log em arquivo (Persistência)
    logger.add(
        LOG_FILE,
        rotation="10 MB",
        retention="10 days",
        level="INFO",
        # Padrão de mercado: Data Hora | Nível | Origem (Módulo:Linha) | Mensagem
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} | {message}"
    )
    
    # Log em console (Monitoramento)
    logger.add(
        sys.stderr,
        level="INFO",
        # Formato visual com destaque para a origem do log
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <magenta>{name}:{line}</magenta> | <cyan>{message}</cyan>"
    )
    
    return logger

# =========================
# Sanitização e Processamento
# =========================

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
            for element in soup(["script", "style", "head", "title", "meta", "[document]", "noscript"]):
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