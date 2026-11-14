from pydantic import BaseModel, Field, ValidationError, field_validator

# =========================
# Schemas de Dados (Pydantic)
# =========================

class ClassificationResult(BaseModel):
    """
    Estrutura de dados para a resposta classificada pela IA.
    """
    category: str = Field(..., description="O CÓDIGO da regra escolhida ou 'IGNORAR'.")
    summary: str = Field(..., description="Resumo executivo do e-mail. Máximo 2 frases.")
    justification: str = Field(..., description="Explicação técnica da escolha da categoria.")
    urgency: int = Field(..., description="Nível de urgência (1-5).")
    thread_summary: str = Field(
        "", description="Resumo consolidado da conversa inteira (histórico + este e-mail). Máximo 3 frases."
    )

    @field_validator("thread_summary", mode="before")
    @classmethod
    def _none_to_empty(cls, value):
        return "" if value is None else value

    @field_validator("category", mode="before")
    @classmethod
    def _normalize_category(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("urgency", mode="before")
    @classmethod
    def _clamp_urgency(cls, value):
        # Modelos às vezes devolvem "3", 3.0 ou valores fora da faixa: normaliza em vez de falhar.
        try:
            return max(1, min(5, int(float(value))))
        except (TypeError, ValueError):
            return 1

# =========================
# Validação de Modelagem (QA)
# =========================

if __name__ == "__main__":
    print("--- Diagnóstico de Models ---")

    # Validação de entrada íntegra
    try:
        modelo = ClassificationResult(
            category="FINANCEIRO",
            summary="Pagamento pendente identificado.",
            justification="Termos 'boleto' e 'vencimento' encontrados.",
            urgency=5
        )
        print(f"[SUCESSO] Schema validado: {modelo.model_dump_json()}")
    except ValidationError as e:
        print(f"[ERRO] Falha na validação de schema íntegro: {e}")

    # Validação de restrição de integridade (Campos ausentes)
    try:
        ClassificationResult(category="ERRO")
        print("[ERRO] O modelo permitiu dados parciais (Inseguro).")
    except ValidationError:
        print("[SUCESSO] Restrição de integridade validada: Dados incompletos rejeitados.")
