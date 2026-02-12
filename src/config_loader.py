import json
import os
from typing import Dict, List, Optional
from dotenv import load_dotenv
from src.utils import setup_logger
from src.paths import RULES_FILE, ENV_FILE

# =========================
# Inicialização de Ambiente
# =========================

load_dotenv(ENV_FILE)
logger = setup_logger()

# Configurações Globais do Sistema
MODEL_NAME = "gemini-2.5-flash-lite"
CUTOFF_DATE_STR = "01/01/2026 10:00"
COOLDOWN_SECONDS = 5
RETRY_BASE_WAIT = 45
MAX_RETRIES_IA = 3
MAX_BODY_CHARS_IA = 4000

# Variáveis de Conectividade
ENV_IMAP_SERVER = os.getenv("IMAP_SERVER")
ENV_SMTP_SERVER = os.getenv("SMTP_SERVER")
ENV_EMAIL_USER = os.getenv("EMAIL_USER")
ENV_EMAIL_PASS = os.getenv("EMAIL_PASS")

class ConfigLoader:
    """
    Gerencia o carregamento de regras de negócio e credenciais.
    """
    def __init__(self):
        self.rules_path = RULES_FILE
        self.raw_data = self._load_rules()
        self.flat_lookup = self._flatten_rules()
        self.all_keywords = self._extract_all_keywords()

    # =========================
    # Métodos Internos de Carga
    # =========================

    def _load_rules(self) -> Dict:
        if not self.rules_path.exists():
            logger.critical(f"Arquivo de regras ausente: {self.rules_path}")
            return {}
        try:
            with open(self.rules_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                logger.info(f"Regras carregadas com sucesso: {len(data)} grupos identificados.")
                return data
        except Exception as e:
            logger.critical(f"Erro de integridade no JSON de regras: {str(e)}")
            return {}

    def _flatten_rules(self) -> Dict[str, str]:
        lookup = {}
        for _, dados in self.raw_data.items():
            regras = dados.get("regras", {})
            for codigo, info in regras.items():
                lookup[codigo] = info.get("email_destino")
        return lookup

    def _extract_all_keywords(self) -> List[str]:
        keywords = []
        for _, dados in self.raw_data.items():
            kws = dados.get("palavras_chaves_grupo", [])
            keywords.extend([k.strip().lower() for k in kws if k.strip()])
        return list(set(keywords))

    # =========================
    # Interface de Dados (AI & Services)
    # =========================

    def get_prompt_context(self) -> str:
        """
        Gera o mapeamento textual para o System Prompt da IA.
        """
        lines = []
        for grupo, dados in self.raw_data.items():
            keywords = ", ".join(dados.get("palavras_chaves_grupo", []))
            lines.append(f"\n=== GRUPO: {grupo} ===")
            lines.append(f"   [Contexto/Keywords: {keywords}]")
            for codigo, info in dados.get("regras", {}).items():
                lines.append(f"   -> CÓDIGO: {codigo} | Descrição: {info.get('descricao')}")
        return "\n".join(lines)

    def get_target_email(self, category_key: str) -> Optional[str]:
        return self.flat_lookup.get(category_key)

# =========================
# Validação de Unidade (QA)
# =========================

if __name__ == "__main__":
    logger.info("Iniciando diagnóstico de ConfigLoader...")
    loader = ConfigLoader()
    
    if not loader.raw_data:
        logger.warning(f"Ambiente de teste incompleto: {RULES_FILE} não encontrado.")
    else:
        print(f"--- Relatório de Configuração ---")
        print(f"Grupos ativos: {list(loader.raw_data.keys())}")
        print(f"Palavras-chave monitoradas: {len(loader.all_keywords)}")
        
        context_preview = loader.get_prompt_context()
        print("\n--- Integridade do Prompt Contextual ---")
        print(context_preview)