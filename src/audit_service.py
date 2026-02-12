import pandas as pd
from datetime import datetime
from loguru import logger
from src.models import ClassificationResult
from src.paths import CSV_FILE

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
        if not self.filepath.exists():
            # ADICIONADO: Coluna 'Copias'
            columns = ["Data", "Remetente", "Copias", "Assunto", "Categoria", "Resumo", "Destino"]
            pd.DataFrame(columns=columns).to_csv(self.filepath, index=False)

    def register(self, sender: str, cc: str, subject: str, res: ClassificationResult, destination: str):
        """
        Registra uma nova transação de e-mail no histórico de auditoria.
        """
        try:
            entry = {
                "Data": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Remetente": sender,
                "Copias": cc,  # ADICIONADO: Campo de cópia
                "Assunto": subject,
                "Categoria": res.category,
                "Resumo": res.summary,
                "Destino": destination or "NÃO ENCAMINHADO"
            }
            pd.DataFrame([entry]).to_csv(self.filepath, mode='a', header=False, index=False)
            
        except Exception as e:
            logger.error(f"Falha ao registrar auditoria em disco: {str(e)}")

# =========================
# Validação de Unidade (QA)
# =========================

if __name__ == "__main__":
    from src.utils import setup_logger
    setup_logger()
    
    with logger.contextualize(user="machine"):
        logger.info("Iniciando teste de integridade do AuditService")
        audit = AuditService()
        
        res_teste = ClassificationResult(
            category="TESTE_MODULO",
            summary="Execução de teste unitário do módulo audit.",
            justification="Verificação de escrita em disco.",
            urgency=1
        )
        
        # Teste atualizado com argumento CC
        audit.register("tester@local", "copia@local", "Teste Unitário Audit", res_teste, "admin@local")
        
        if CSV_FILE.exists():
            df = pd.read_csv(CSV_FILE)
            ultimo = df.iloc[-1]
            
            if ultimo["Categoria"] == "TESTE_MODULO":
                logger.success("Teste de persistência concluído: Registro verificado.")
            else:
                logger.error("Divergência de dados detectada na leitura do CSV.")