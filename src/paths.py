from pathlib import Path

# =========================
# Definição de Estrutura de Diretórios
# =========================

# Define a raiz do projeto (ancorado em relação ao diretório src)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"

# =========================
# Mapeamento de Arquivos
# =========================

ENV_FILE = CONFIG_DIR / ".env"
RULES_FILE = CONFIG_DIR / "regras.json"
LOG_FILE = LOGS_DIR / "app.log"
CSV_FILE = DATA_DIR / "historico_emails.csv"
DB_FILE = DATA_DIR / "emails.db"

# =========================
# Inicialização de Ambiente
# =========================

# Assegura a existência dos diretórios de persistência e telemetria
LOGS_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

# =========================
# Validação de Caminhos (QA)
# =========================

if __name__ == "__main__":
    print("--- Diagnóstico de Caminhos ---")
    print(f"Raiz do Projeto: {PROJECT_ROOT}")
    print(f"Configuração [.env]: {'OK' if ENV_FILE.exists() else 'AUSENTE'}")
    print(f"Regras [JSON]: {'OK' if RULES_FILE.exists() else 'AUSENTE'}")
    print(f"Diretório Logs: {'OK' if LOGS_DIR.exists() else 'ERRO'}")
    print(f"Diretório Dados: {'OK' if DATA_DIR.exists() else 'ERRO'}")