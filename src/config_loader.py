import json
import os
from typing import Dict, List, Optional
from dotenv import load_dotenv
from src.utils import setup_logger
from src.paths import RULES_FILE, ENV_FILE

# =========================
# Inicialização de Ambiente
# =========================

# Variáveis já definidas no ambiente (ex.: Docker) têm prioridade sobre o arquivo.
load_dotenv(ENV_FILE)
logger = setup_logger()


def _env_str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return value.strip() if value is not None else default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        logger.warning(f"Valor inválido para {name}='{raw}'. Usando padrão: {default}")
        return default


def _env_bool(name: str) -> Optional[bool]:
    """Retorna None quando a variável não está definida (tri-state)."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    return raw.strip().lower() in ("1", "true", "yes", "sim", "on")


# =========================
# Configurações de IA
# =========================

# Provedores suportados: "nvidia" (Nemotron e demais modelos do NVIDIA NIM) ou "gemini"
AI_PROVIDER = _env_str("AI_PROVIDER", "nvidia").lower()

NVIDIA_API_KEY = _env_str("NVIDIA_API_KEY")
NVIDIA_BASE_URL = _env_str("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_MODEL = _env_str("NVIDIA_MODEL", "nvidia/nemotron-3.5-super-vl-120b-a12b")
# Padrão: false (resposta direta, mais rápida). Definida VAZIA = não envia o
# parâmetro (para modelos que não aceitam chat_template_kwargs).
NVIDIA_ENABLE_THINKING = (
    False if os.getenv("NVIDIA_ENABLE_THINKING") is None else _env_bool("NVIDIA_ENABLE_THINKING")
)

GEMINI_MODEL = _env_str("GEMINI_MODEL", "gemini-2.5-flash-lite")

MODEL_NAME = NVIDIA_MODEL if AI_PROVIDER == "nvidia" else GEMINI_MODEL

AI_TIMEOUT_SECONDS = _env_int("AI_TIMEOUT_SECONDS", 120)
AI_MAX_TOKENS = _env_int("AI_MAX_TOKENS", 2048)
MAX_RETRIES_IA = max(1, _env_int("MAX_RETRIES_IA", 3))
RETRY_BASE_WAIT = _env_int("RETRY_BASE_WAIT", 45)
MAX_BODY_CHARS_IA = _env_int("MAX_BODY_CHARS_IA", 4000)

# =========================
# Configurações de Execução
# =========================

# "agora" = momento da primeira execução (persistido no banco) | DD/MM/AAAA HH:MM = data fixa
CUTOFF_DATE_STR = _env_str("CUTOFF_DATE", "agora") or "agora"
# true = só encaminha e-mails com palavras-chave (os demais são apenas resumidos e salvos)
REQUIRE_KEYWORDS_TO_FORWARD = _env_bool("REQUIRE_KEYWORDS_TO_FORWARD") is not False
# Marca o e-mail como lido na caixa após tratá-lo
MARK_AS_SEEN = _env_bool("MARK_AS_SEEN") is not False
COOLDOWN_SECONDS = _env_int("COOLDOWN_SECONDS", 5)
# Intervalo entre ciclos no modo contínuo (python main.py --loop)
POLL_INTERVAL_SECONDS = max(10, _env_int("POLL_INTERVAL_SECONDS", 120))
# Após N falhas técnicas no mesmo e-mail, ele é marcado como lido e abandonado
MAX_FAILURES_PER_EMAIL = max(1, _env_int("MAX_FAILURES_PER_EMAIL", 3))

# =========================
# Variáveis de Conectividade
# =========================

ENV_IMAP_SERVER = _env_str("IMAP_SERVER")
ENV_IMAP_PORT = _env_int("IMAP_PORT", 993)
ENV_SMTP_SERVER = _env_str("SMTP_SERVER")
ENV_SMTP_PORT = _env_int("SMTP_PORT", 587)
ENV_EMAIL_USER = _env_str("EMAIL_USER")
ENV_EMAIL_PASS = _env_str("EMAIL_PASS")
NETWORK_TIMEOUT_SECONDS = _env_int("NETWORK_TIMEOUT_SECONDS", 60)


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
            logger.critical(
                f"Arquivo de regras ausente: {self.rules_path}. "
                f"Copie config/regras.example.json para config/regras.json e ajuste."
            )
            return {}
        try:
            with open(self.rules_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                logger.critical("JSON de regras inválido: a raiz deve ser um objeto.")
                return {}
            logger.info(f"Regras carregadas com sucesso: {len(data)} grupos identificados.")
            return data
        except Exception as e:
            logger.critical(f"Erro de integridade no JSON de regras: {str(e)}")
            return {}

    def _flatten_rules(self) -> Dict[str, str]:
        lookup = {}
        for grupo, dados in self.raw_data.items():
            regras = dados.get("regras", {})
            for codigo, info in regras.items():
                destino = info.get("email_destino") or ""
                # Aceita lista ou texto separado por vírgula/ponto e vírgula (vários destinatários)
                if isinstance(destino, str):
                    destino = destino.replace(";", ",").split(",")
                destino = ", ".join(d.strip() for d in destino if d and d.strip())
                if not destino:
                    # Sem destino a regra nunca poderia ser encaminhada: fica fora do prompt.
                    logger.warning(f"Regra '{codigo}' ({grupo}) sem 'email_destino'. Regra desativada.")
                    continue
                if codigo in lookup:
                    logger.warning(f"Código de regra duplicado: '{codigo}'. Prevalece a última definição.")
                lookup[codigo] = destino
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
            regras_ativas = {
                codigo: info for codigo, info in dados.get("regras", {}).items()
                if codigo in self.flat_lookup
            }
            if not regras_ativas:
                continue
            keywords = ", ".join(dados.get("palavras_chaves_grupo", []))
            lines.append(f"\n=== GRUPO: {grupo} ===")
            lines.append(f"   [Contexto/Keywords: {keywords}]")
            for codigo, info in regras_ativas.items():
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

    print(f"Provedor de IA: {AI_PROVIDER} | Modelo: {MODEL_NAME}")
    if not loader.raw_data:
        logger.warning(f"Ambiente de teste incompleto: {RULES_FILE} não encontrado.")
    else:
        print("--- Relatório de Configuração ---")
        print(f"Grupos ativos: {list(loader.raw_data.keys())}")
        print(f"Palavras-chave monitoradas: {len(loader.all_keywords)}")

        context_preview = loader.get_prompt_context()
        print("\n--- Integridade do Prompt Contextual ---")
        print(context_preview)
