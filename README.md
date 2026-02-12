# ENCAMINHAMENTO_EMAILS_IA 📩🤖

Este projeto é um sistema de automação corporativa desenvolvido em Python para triagem e encaminhamento inteligente de e-mails.
O sistema monitora uma caixa de entrada via IMAP, filtra mensagens relevantes e utiliza Inteligência Artificial (Google Gemini via LangChain) para analisar o contexto e classificar a demanda conforme regras de negócio predefinidas.

O principal diferencial é a funcionalidade de **Smart Reply-To**: ao encaminhar a demanda para o setor responsável (ex: Financeiro), o robô configura automaticamente o cabeçalho de resposta. Assim, quando o colaborador interno clica em "Responder", a mensagem é endereçada diretamente ao cliente original e a todos os envolvidos em cópia, garantindo fluidez na comunicação.

------------------------------------------------------------
🚀 FUNCIONALIDADES
------------------------------------------------------------

### 🧠 Inteligência & Triagem
- **Leitura Otimizada (IMAP):** Processa apenas e-mails não lidos (UNSEEN) e aplica filtros temporais (data de corte).
- **Triagem Híbrida:** Utiliza um pré-filtro local de palavras-chave para acionar a IA apenas em mensagens relevantes, otimizando custos e performance.
- **Classificação Semântica (IA):** O agente de IA analisa o assunto e o corpo do e-mail (sanitizado) para determinar a categoria correta (ex: FINANCEIRO, SUPORTE, COMERCIAL).
- **Validação Estruturada:** Utiliza Pydantic para garantir que a IA retorne dados estritamente dentro do esquema esperado.

### 📧 Engenharia de E-mail
- **Smart Reply-To:** O e-mail encaminhado preserva o fluxo de comunicação original. O campo `Reply-To` é preenchido dinamicamente com o remetente original + cópias (CC), excluindo o próprio robô da lista.
- **Visual Corporativo (HTML Card):** O encaminhamento possui um layout moderno e limpo, contendo badges de categoria, resumo executivo gerado pela IA e alertas visuais sobre o redirecionamento de resposta.
- **Gestão de Anexos:** Todos os arquivos anexados à mensagem original são preservados e reencaminhados.

### 🛡️ Auditoria & Observabilidade
- **Logs Estruturados:** Sistema de logs (Loguru) com rotação automática de arquivos e saída colorida no console.
- **Rastreabilidade (CSV):** Registro automático de todas as decisões tomadas em `data/historico_emails.csv` (Data, Remetente, Categoria, Justificativa e Destino).

------------------------------------------------------------
📂 ESTRUTURA DO PROJETO
------------------------------------------------------------

O projeto segue uma organização modular para facilitar a manutenção:
```
encaminhamento_emails_ia/
├── config/                  # Configurações do sistema
│   ├── .env                 # Credenciais e chaves de API (Sensível)
│   └── regras.json          # Definição das regras de negócio
│
├── data/                    # Persistência de dados
│   └── historico_emails.csv # Histórico de auditoria
│
├── logs/                    # Logs de execução
│   └── app.log              # Arquivo de log rotativo
│
├── src/                     # Código Fonte (Core)
│   ├── ai_agent.py          # Agente LangChain e Prompts
│   ├── email_service.py     # Lógica IMAP/SMTP e Smart Reply
│   ├── config_loader.py     # Carregamento de configurações
│   ├── audit_service.py     # Gestão de CSV
│   ├── utils.py             # Sanitização de HTML e Helpers
│   ├── models.py            # Schemas de dados (Pydantic)
│   └── paths.py             # Gerenciamento de diretórios
│
├── main.py                  # Executável Principal (Entry Point)
└── requirements.txt         # Dependências do Python
```

------------------------------------------------------------
🛠️ TECNOLOGIAS UTILIZADAS
------------------------------------------------------------

- **Linguagem:** Python 3.10+
- **IA Generativa:** LangChain + Google Gemini (Flash Lite)
- **Validação de Dados:** Pydantic
- **Rede e Protocolos:** imaplib, smtplib, email (Standard Lib)
- **Manipulação de HTML:** BeautifulSoup4
- **Logging:** Loguru
- **Configuração:** Python-Dotenv

------------------------------------------------------------
📋 PRÉ-REQUISITOS
------------------------------------------------------------

1. Python 3.10 ou superior instalado.
2. Conta de e-mail com acesso IMAP e SMTP habilitado (Gmail, Outlook, etc.).
3. Chave de API do Google Gemini (Google AI Studio).

------------------------------------------------------------
🔧 INSTALAÇÃO E CONFIGURAÇÃO
------------------------------------------------------------

1. **Instale as dependências:**
   pip install -r requirements.txt

2. **Configure as variáveis de ambiente:**
   Crie o arquivo `config/.env` com o seguinte conteúdo:

   IMAP_SERVER=imap.seuprovedor.com
   SMTP_SERVER=smtp.seuprovedor.com
   EMAIL_USER=seu_email@empresa.com
   EMAIL_PASS=sua_senha_de_app
   GOOGLE_API_KEY=sua_chave_api_gemini

3. **Defina as Regras de Negócio:**
   Edite o arquivo `config/regras.json` para definir como a IA deve classificar os e-mails.

   Exemplo de `regras.json`:
```
   {
     "FINANCEIRO": {
       "palavras_chaves_grupo": ["boleto", "fatura", "nota fiscal", "pagamento"],
       "regras": {
         "FIN_ENTRADA": {
           "descricao": "Comprovantes de pagamento ou dúvidas sobre cobrança",
           "email_destino": "financeiro@empresa.com"
         }
       }
     },
     "SUPORTE": {
       "palavras_chaves_grupo": ["erro", "falha", "sistema", "acesso"],
       "regras": {
         "SUP_TECNICO": {
           "descricao": "Relatos de problemas técnicos ou bugs",
           "email_destino": "dev@empresa.com"
         }
       }
     }
   }
```

------------------------------------------------------------
🚀 MODO DE USO
------------------------------------------------------------

Para iniciar o robô, execute o arquivo principal a partir da raiz do projeto:

python main.py

O sistema irá:
1. Conectar ao servidor de e-mail.
2. Buscar mensagens não lidas que correspondam à data de corte.
3. Filtrar por palavras-chave locais.
4. Enviar o conteúdo para a IA classificar.
5. Encaminhar o e-mail para o destino correto com a configuração de Smart Reply.
6. Registrar a ação no CSV e aguardar o tempo de cooldown.

------------------------------------------------------------
ℹ️ DETALHES TÉCNICOS
------------------------------------------------------------

**Smart Reply-To:**
Diferente de um encaminhamento padrão, este sistema atua como um "proxy transparente". O e-mail chega na caixa do destinatário final (ex: Financeiro) vindo do robô, mas o cabeçalho técnico `Reply-To` contém a lista de e-mails originais (Remetente + CCs). Isso elimina a necessidade do funcionário copiar e colar e-mails manualmente.

**Auditoria:**
O arquivo `data/historico_emails.csv` é gerado automaticamente e serve como log de conformidade, registrando quem enviou, qual foi o assunto, como a IA classificou e para onde foi encaminhado.
