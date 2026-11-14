# ENCAMINHAMENTO_EMAILS_IA 📩🤖

Este projeto é um sistema de automação corporativa desenvolvido em Python para triagem e encaminhamento inteligente de e-mails.
O sistema monitora uma caixa de entrada via IMAP, filtra mensagens relevantes e utiliza Inteligência Artificial (NVIDIA Nemotron ou Google Gemini, via LangChain) para resumir cada mensagem, analisar o contexto e classificar a demanda conforme regras de negócio predefinidas.

O principal diferencial é a funcionalidade de **Smart Reply-To**: ao encaminhar a demanda para o setor responsável (ex: Financeiro), o robô configura automaticamente o cabeçalho de resposta. Assim, quando o colaborador interno clica em "Responder", a mensagem é endereçada diretamente ao cliente original e a todos os envolvidos em cópia, garantindo fluidez na comunicação.

------------------------------------------------------------
🚀 FUNCIONALIDADES
------------------------------------------------------------

### 🧠 Inteligência & Triagem
- **Leitura Contínua (IMAP):** Lê todos os e-mails recebidos a partir do momento da primeira execução (lidos ou não). O marco fica salvo no banco, então reinícios não perdem mensagens.
- **Resumo de Todos os E-mails:** Cada mensagem é resumida pela IA e salva no banco local, identificada pelo seu `Message-ID`.
- **Conversas (Threads):** Respostas são agrupadas pela cadeia `References`/`In-Reply-To`; a IA recebe o histórico e mantém um resumo consolidado da conversa.
- **Trava de Palavras-chave:** Por padrão só são encaminhados e-mails que contenham palavras-chave do `regras.json` (`REQUIRE_KEYWORDS_TO_FORWARD`); os demais são apenas resumidos.
- **Tolerância a Falhas:** Erros de IA ou de envio não descartam o e-mail: ele é tentado de novo no ciclo seguinte (até `MAX_FAILURES_PER_EMAIL`).
- **Classificação Semântica (IA):** O agente de IA analisa o assunto e o corpo do e-mail (sanitizado) para determinar a categoria correta (ex: FINANCEIRO, SUPORTE, COMERCIAL).
- **Validação Estruturada:** Utiliza Pydantic para garantir que a IA retorne dados estritamente dentro do esquema esperado.

### 📧 Engenharia de E-mail
- **Smart Reply-To:** O e-mail encaminhado preserva o fluxo de comunicação original. O campo `Reply-To` é preenchido dinamicamente com o remetente original + cópias (CC), excluindo o próprio robô da lista.
- **Visual Corporativo (HTML Card):** O encaminhamento possui um layout moderno e limpo, contendo badges de categoria, resumo executivo gerado pela IA e alertas visuais sobre o redirecionamento de resposta.
- **Gestão de Anexos:** Todos os arquivos anexados à mensagem original são preservados e reencaminhados.

### 🛡️ Auditoria & Observabilidade
- **Logs Estruturados:** Sistema de logs (Loguru) com rotação automática de arquivos e saída colorida no console.
- **Banco Local (SQLite):** `data/emails.db` guarda todos os e-mails (corpo, resumo, categoria, urgência, status) e as conversas. Não exige servidor de banco.
- **Rastreabilidade (CSV):** Registro automático de todas as decisões tomadas em `data/historico_emails.csv` (Data, Remetente, Categoria, Urgência, Resumo, Justificativa e Destino).

------------------------------------------------------------
📂 ESTRUTURA DO PROJETO
------------------------------------------------------------

O projeto segue uma organização modular para facilitar a manutenção:
```
encaminhamento_emails_ia/
├── config/                  # Configurações do sistema
│   ├── .env                 # Credenciais e chaves de API (Sensível, não versionado)
│   ├── .env.example         # Modelo do .env
│   ├── regras.json          # Regras de negócio reais (não versionado)
│   └── regras.example.json  # Modelo do regras.json
│
├── data/                    # Persistência de dados
│   ├── emails.db            # Banco SQLite (e-mails, resumos, conversas)
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
│   ├── database.py          # Banco SQLite (e-mails e conversas)
│   ├── utils.py             # Sanitização de HTML e Helpers
│   ├── models.py            # Schemas de dados (Pydantic)
│   └── paths.py             # Gerenciamento de diretórios
│
├── Dockerfile               # Imagem do serviço
├── docker-compose.yml       # Execução contínua em container
├── main.py                  # Executável Principal (Entry Point)
└── requirements.txt         # Dependências do Python
```

------------------------------------------------------------
🛠️ TECNOLOGIAS UTILIZADAS
------------------------------------------------------------

- **Linguagem:** Python 3.10+
- **IA Generativa:** LangChain + NVIDIA NIM (Nemotron) ou Google Gemini
- **Banco de Dados:** SQLite (Standard Lib)
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
3. Chave de API da NVIDIA (https://build.nvidia.com) ou do Google Gemini (Google AI Studio).
4. Docker (opcional, para execução contínua).

------------------------------------------------------------
🔧 INSTALAÇÃO E CONFIGURAÇÃO
------------------------------------------------------------

1. **Instale as dependências:**
   pip install -r requirements.txt

2. **Configure as variáveis de ambiente:**
   Copie `config/.env.example` para `config/.env` e preencha, no mínimo:

   IMAP_SERVER=imap.seuprovedor.com
   SMTP_SERVER=smtp.seuprovedor.com
   EMAIL_USER=seu_email@empresa.com
   EMAIL_PASS=sua_senha_de_app
   AI_PROVIDER=nvidia
   NVIDIA_API_KEY=nvapi-...

   Para usar o Gemini: `AI_PROVIDER=gemini` e `GOOGLE_API_KEY=...`.
   **Opções avançadas** (todas opcionais; só adicione ao `.env` o que quiser mudar):

   | Variável | Padrão | Para que serve |
   |---|---|---|
   | `REQUIRE_KEYWORDS_TO_FORWARD` | `true` | `true` só encaminha e-mails com palavras-chave; `false` deixa a IA decidir sobre todos |
   | `CUTOFF_DATE` | `agora` | Ler a partir da primeira execução, ou de uma data fixa `DD/MM/AAAA HH:MM` |
   | `POLL_INTERVAL_SECONDS` | `120` | Intervalo entre verificações no modo contínuo |
   | `COOLDOWN_SECONDS` | `5` | Pausa entre e-mails classificados |
   | `MARK_AS_SEEN` | `true` | Marca o e-mail como lido após tratá-lo |
   | `MAX_FAILURES_PER_EMAIL` | `3` | Falhas toleradas por e-mail antes de desistir dele |
   | `IMAP_PORT` / `SMTP_PORT` | `993` / `587` | Portas (SMTP `465` usa SSL) |
   | `NVIDIA_MODEL` | `nvidia/nemotron-3.5-super-vl-120b-a12b` | Modelo do catálogo NVIDIA |
   | `NVIDIA_ENABLE_THINKING` | `false` | Raciocínio do modelo; deixe vazia para modelos que não aceitam o parâmetro |
   | `GEMINI_MODEL` | `gemini-2.5-flash-lite` | Modelo quando `AI_PROVIDER=gemini` |
   | `MAX_RETRIES_IA` / `RETRY_BASE_WAIT` | `3` / `45` | Tentativas e espera (s) em falhas temporárias da IA |
   | `MAX_BODY_CHARS_IA` | `4000` | Máximo de caracteres do corpo enviados à IA |
   | `AI_TIMEOUT_SECONDS` / `AI_MAX_TOKENS` | `120` / `2048` | Limites da chamada de IA |
   | `NETWORK_TIMEOUT_SECONDS` | `60` | Timeout de IMAP/SMTP |
   | `TZ` | `America/Sao_Paulo` | Fuso horário do container Docker |

3. **Defina as Regras de Negócio:**
   Copie `config/regras.example.json` para `config/regras.json` e edite para definir como a IA deve classificar os e-mails.
   O `regras.json` real não é versionado. `email_destino` aceita um endereço ou uma lista (`["a@empresa.com", "b@empresa.com"]`).

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

**Execução única** (um ciclo e encerra):

python main.py

**Execução contínua local** (um ciclo a cada `POLL_INTERVAL_SECONDS`):

python main.py --loop

**Execução contínua com Docker** (reinicia sozinho após falhas ou reboot):

docker compose up -d --build      # sobe o serviço
docker compose logs -f            # acompanha os logs
docker compose restart            # aplica mudanças no .env / regras.json
docker compose down               # para o serviço

**Consultar o banco:**

python -m src.database

A cada ciclo o sistema irá:
1. Conectar ao servidor de e-mail.
2. Buscar as mensagens recebidas desde o início do monitoramento que ainda não foram tratadas.
3. Identificar a conversa (thread) e carregar o histórico já resumido.
4. Enviar o conteúdo para a IA resumir e classificar.
5. Encaminhar o e-mail para o destino correto com a configuração de Smart Reply (se houver palavras-chave e categoria).
6. Salvar tudo no banco e no CSV e aguardar o tempo de cooldown.

Status possíveis no banco: `ENCAMINHADO`, `IGNORADO` (IA não encontrou categoria), `SEM_PALAVRA_CHAVE` (resumido, mas sem encaminhar), `ERRO` (será tentado de novo) e `ABANDONADO` (excedeu as tentativas).

------------------------------------------------------------
ℹ️ DETALHES TÉCNICOS
------------------------------------------------------------

**Smart Reply-To:**
Diferente de um encaminhamento padrão, este sistema atua como um "proxy transparente". O e-mail chega na caixa do destinatário final (ex: Financeiro) vindo do robô, mas o cabeçalho técnico `Reply-To` contém a lista de e-mails originais (Remetente + CCs). Isso elimina a necessidade do funcionário copiar e colar e-mails manualmente.

**Auditoria:**
O arquivo `data/historico_emails.csv` é gerado automaticamente e serve como log de conformidade, registrando quem enviou, qual foi o assunto, como a IA classificou e para onde foi encaminhado.
