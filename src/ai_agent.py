from time import sleep
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from loguru import logger

from src.models import ClassificationResult
from src.config_loader import ConfigLoader, MODEL_NAME, MAX_RETRIES_IA, RETRY_BASE_WAIT, MAX_BODY_CHARS_IA

class AiAgent:
    """
    Orquestrador de inteligência artificial para classificação estruturada de e-mails.
    """
    def __init__(self, config: ConfigLoader):
        # =========================
        # Inicialização do Modelo
        # =========================
        logger.info(f"Configurando Agente IA com modelo: {MODEL_NAME}")
        self.config = config
        self.llm = ChatGoogleGenerativeAI(model=MODEL_NAME, temperature=0, max_retries=0)
        self.structured_llm = self.llm.with_structured_output(ClassificationResult)
        
        self.valid_codes = list(self.config.flat_lookup.keys()) + ["IGNORAR"]
        codes_str = ", ".join(self.valid_codes)

        # =========================
        # Definição de Prompts (RAG)
        # =========================
        system_msg = f"""Você é um assistente executivo de triagem de emails.
1. Analise o remetente e o texto LIMPO do email.
2. Gere um RESUMO curto (1-2 frases).
3. Classifique usando EXATAMENTE um dos códigos: [{codes_str}]

{self.config.get_prompt_context()}
"""
        self.prompt_main = ChatPromptTemplate.from_messages([
            ("system", system_msg),
            ("human", "Remetente: {sender}\nAssunto: {subject}\n\nConteúdo: {body}")
        ])
        
        correction_sys = f"Erro no código anterior. Escolha um válido: [{codes_str}]"
        self.prompt_correction = ChatPromptTemplate.from_messages([
            ("system", correction_sys),
            ("human", "Erro: '{invalid_cat}'. Email: {sender} | {subject}")
        ])
        
        self.chain_main = self.prompt_main | self.structured_llm
        self.chain_correction = self.prompt_correction | self.structured_llm
        logger.success("Cadeias de execução IA inicializadas com sucesso.")

    def classify(self, subject: str, clean_body: str, sender: str) -> ClassificationResult:
        """
        Executa a classificação do e-mail com lógica de re-tentativa e autocorreção.
        """
        ia_input_body = clean_body[:MAX_BODY_CHARS_IA] if clean_body else "Conteúdo Vazio"
        
        # =========================
        # Loop de Processamento IA
        # =========================
        for attempt in range(MAX_RETRIES_IA):
            try:
                logger.info(f"Iniciando tentativa de classificação {attempt + 1}/{MAX_RETRIES_IA} para: {sender}")
                
                res = self.chain_main.invoke({
                    "sender": sender, 
                    "subject": subject, 
                    "body": ia_input_body
                })
                
                # Validação de integridade da categoria
                if res.category != "IGNORAR" and res.category not in self.config.flat_lookup:
                    logger.warning(f"Detectada categoria inválida ({res.category}). Acionando autocorreção.")
                    res = self.chain_correction.invoke({
                        "invalid_cat": res.category, 
                        "sender": sender, 
                        "subject": subject
                    })
                
                if res.category in self.valid_codes:
                    logger.success(f"Classificação finalizada: {res.category} | Remetente: {sender}")
                    return res
                
                logger.error(f"Falha de consistência pós-correção. Categoria retornada: {res.category}")
                return ClassificationResult(
                    category="IGNORAR", 
                    summary="Erro IA", 
                    justification="Alucinação persistente na categoria", 
                    urgency=1
                )

            except Exception as e:
                if "429" in str(e):
                    wait_time = RETRY_BASE_WAIT * (attempt + 1)
                    logger.warning(f"Limite de quota atingido (429). Retentativa em {wait_time}s.")
                    sleep(wait_time)
                else:
                    logger.exception(f"Erro inesperado na execução da IA: {str(e)}")
                    return ClassificationResult(
                        category="IGNORAR", 
                        summary="Erro Técnico", 
                        justification=str(e), 
                        urgency=1
                    )
        
        logger.error(f"Esgotadas as tentativas de classificação para o e-mail de: {sender}")
        return ClassificationResult(
            category="IGNORAR", 
            summary="Timeout", 
            justification="Falha na API após múltiplas tentativas (Max Retries)", 
            urgency=1
        )

if __name__ == "__main__":
    from src.utils import setup_logger
    setup_logger()
    
    # =========================
    # Testes Unitários de Integração
    # =========================
    logger.info("Iniciando testes de validação de prompt...")

    class MockCfg:
        flat_lookup = {"FINANCEIRO": "fin@test.com", "SUPORTE": "sup@test.com"}
        def get_prompt_context(self): return "Regra FINANCEIRO: Boletos."
    
    agent = AiAgent(MockCfg())
    
    msg_formatada = agent.prompt_main.format_messages(
        sender="cliente@gmail.com", 
        subject="Envio do Comprovante", 
        body="Segue anexo."
    )
    prompt_texto = msg_formatada[0].content
    
    print("\n--- System Prompt Gerado ---")
    print(prompt_texto) 
    
    # Validações de integridade
    assert "FINANCEIRO" in prompt_texto
    assert "Boletos" in prompt_texto
    
    msg_humana = msg_formatada[1].content
    assert "cliente@gmail.com" in msg_humana, "Variável sender não injetada corretamente no prompt."
    
    logger.success("Testes de construção de prompt concluídos com êxito.")