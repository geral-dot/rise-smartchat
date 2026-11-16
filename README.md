# RISE SmartChat 0.2 · Integração controlada com Chatwoot

**RISE PDF — RISE BLACK `#050006` · RISE LIME `#BECC43`**

A versão 0.2 preserva todas as funções do MVP 0.1 e acrescenta a primeira camada real de integração com o Chatwoot. **Não inclui o Chatwoot instalado, nem liga automaticamente o WhatsApp, nem envia respostas da IA sem validação humana.** Está limitada à utilização interna da RISE PDF; multiempresa fica para fase posterior.

## Funcionalidades da versão 0.2

- Novo separador **Atendimento Chatwoot**: lista conversas da conta configurada, consulta histórico, permite escrever e enviar mensagens do operador (com confirmação explícita).
- Geração de **rascunhos com IA** a partir de FAQs aprovadas, quando existe `OPENAI_API_KEY`. Estes são editáveis, nunca enviados automaticamente.
- Endpoint `/api/webhooks/chatwoot` com verificação **HMAC-SHA256**, janela de cinco minutos, identificação da conta e deduplicação de eventos.
- Eventos guardados num registo mínimo com metadados de conversa; mensagens pessoais não são guardadas no registo de eventos (apenas breve pré-visualização, que deve ser abrangida pela política de retenção).
- Estado de pausa por conversa e pausa automática ao detetar uma mensagem pública de operador. **Não existe motor de autorresposta ativo** nesta versão.
- Endpoints de diagnóstico e testes de verificação de assinatura.

## Arranque local

```bash
cd rise-smartchat-v2
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export RISE_ADMIN_PASSWORD='UMA_PALAVRA_PASSE_FORTE_E_UNICA'
export RISE_SESSION_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
uvicorn main:app --reload
```

Abrir `http://127.0.0.1:8000`. Para Docker: `docker build -t rise-smartchat:0.2 .` e `docker run` com variáveis de ambiente e volume persistente em `/app/data`.

## Ligar ao Chatwoot

1. Instalar **Chatwoot Community Edition** num serviço separado, com PostgreSQL, Redis, HTTPS, email transacional e backups; criar conta RISE.
2. Obter o token de acesso API de um operador autorizado e o ID da conta.
3. Configurar **apenas no servidor**:

```dotenv
CHATWOOT_URL=https://chatwoot.exemplo.pt
CHATWOOT_ACCOUNT_ID=1
CHATWOOT_API_TOKEN=valor_secreto
CHATWOOT_WEBHOOK_SECRET=segredo_do_webhook
OPENAI_API_KEY=chave_opcional_para_rascunhos
OPENAI_MODEL=gpt-4.1-mini
RISE_SECURE_COOKIES=true
```

4. No Chatwoot, configurar webhook para `https://smartchat.exemplo.pt/api/webhooks/chatwoot`, eventos `message_created`, `conversation_created` e `conversation_updated`. Copiar o **segredo de assinatura indicado no Chatwoot**.
5. Verificar em «Integrações» e «Atendimento Chatwoot». Nunca colocar tokens no JavaScript/browser.
6. Só ligar canal de WhatsApp Business Cloud API depois de validar o número e os requisitos da Meta.

**Atenção:** verificar a assinatura numa instalação real de Chatwoot. Existem relatos de versões em que o segredo devolvido pela API não corresponde ao usado na assinatura. Não desativar a verificação HMAC para contornar esse problema. Consulte o guia oficial: https://chatwoot.help/hc/user-guide/articles/1677693021-how-to-use-webhooks

## Segurança e limitações

- Login por palavra-passe única: **adequado apenas a ambiente interno de testes**. Não abrir ao público antes de implementar contas de operador, MFA, controlo de acessos, rate limiting e gestão de sessões.
- A aplicação continua com SQLite; para produção deverá migrar para PostgreSQL, com backups e encriptação em repouso.
- Rascunhos de IA utilizam a API OpenAI; não enviar dados pessoais sensíveis. Rever base legal, subcontratantes e retenção antes de produção.
- As ações do operador enviam efetivamente mensagens se as credenciais Chatwoot estiverem configuradas. Confirmar o destinatário e texto antes de clicar.
- O webhook é idempotente por ID de entrega; a verificação é **fail closed** quando não existe segredo.
- O Chatwoot é a fonte de verdade das mensagens; o SmartChat mantém apenas dados operacionais reduzidos.
- Não existe publicação automática de respostas de IA, sincronização de CRM ou suporte multiempresa nesta versão.

## Testes

```bash
pip install pytest
pytest -q
```

Os testes automáticos cobrem o cálculo de assinaturas, rejeição de eventos expirados e ausência de envio automático. **Não substituem um teste end-to-end contra uma instância real de Chatwoot.**
