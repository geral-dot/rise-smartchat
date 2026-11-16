"""RISE SmartChat v0.1 — MVP interno de demonstração; não é um substituto da inbox Chatwoot."""
import os, sqlite3, secrets, time, json, re
from pathlib import Path
from contextlib import contextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware
import httpx

ROOT=Path(__file__).parent
DATA=Path(os.getenv('RISE_DATA_DIR', str(ROOT/'data')))
DATA.mkdir(parents=True, exist_ok=True)
DB=DATA/'rise.db'
PWD=os.getenv('RISE_ADMIN_PASSWORD','')
SECRET=os.getenv('RISE_SESSION_SECRET','')
if len(PWD)<12 or len(SECRET)<32:
    raise RuntimeError('Configurar RISE_ADMIN_PASSWORD (>=12 caracteres) e RISE_SESSION_SECRET (>=32 caracteres).')
app=FastAPI(title='RISE SmartChat',docs_url=None,redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=SECRET, same_site='lax', https_only=os.getenv('RISE_SECURE_COOKIES','false').lower()=='true', max_age=28800)
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')

FAQS=[
('Quanto custa criar um website?','O investimento depende da estrutura, das funcionalidades e dos objetivos do projeto. Analisamos cada necessidade antes de apresentar uma proposta.'),
('Quanto tempo demora?','O prazo depende da dimensão do projeto e da disponibilidade dos conteúdos. A equipa poderá apresentar uma estimativa após analisar as necessidades.'),
('Trabalham com WordPress?','Sim. Desenvolvemos websites em WordPress e avaliamos a solução adequada a cada projeto.'),
('Fazem lojas online?','Sim. Desenvolvemos lojas online adaptadas às necessidades comerciais e operacionais de cada negócio.'),
('O website fica preparado para SEO?','Podemos integrar boas práticas de SEO no desenvolvimento, com âmbito definido na proposta. Não garantimos posições nos resultados de pesquisa.'),
('Fazem manutenção?','Podemos assegurar manutenção e acompanhamento, com condições ajustadas às necessidades do projeto.')]

@contextmanager
def db():
    conn=sqlite3.connect(DB)
    conn.row_factory=sqlite3.Row
    try: yield conn;conn.commit()
    finally: conn.close()

with db() as c:
    c.executescript('''CREATE TABLE IF NOT EXISTS faqs (id INTEGER PRIMARY KEY, question TEXT NOT NULL, answer TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS conversations (id INTEGER PRIMARY KEY, contact TEXT NOT NULL DEFAULT 'Visitante', stage INTEGER NOT NULL DEFAULT 0, kind TEXT DEFAULT '', goal TEXT DEFAULT '', timing TEXT DEFAULT '', company TEXT DEFAULT '', details TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'bot', created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, conversation_id INTEGER NOT NULL, role TEXT NOT NULL, body TEXT NOT NULL, created_at INTEGER NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
    ''')
    if not c.execute('SELECT 1 FROM faqs LIMIT 1').fetchone():c.executemany('INSERT INTO faqs(question,answer) VALUES(?,?)',FAQS)

@app.middleware('http')
async def security_headers(req,call_next):
    res=await call_next(req)
    res.headers['X-Content-Type-Options']='nosniff'
    res.headers['X-Frame-Options']='DENY'
    res.headers['Referrer-Policy']='no-referrer'
    res.headers['Cache-Control']='no-store'
    return res

def guard(request:Request,mutate=False):
    if not request.session.get('auth'):raise HTTPException(401,'Autenticação necessária')
    if mutate and request.headers.get('x-rise-csrf','')!=request.session.get('csrf'):
        raise HTTPException(403,'CSRF inválido')

def output(con,dbcon):
    d=dict(con)
    d['messages']=[dict(x) for x in dbcon.execute('SELECT role,body,created_at FROM messages WHERE conversation_id=? ORDER BY id',(d['id'],))]
    return d

@app.get('/',response_class=HTMLResponse)
def home():return (ROOT/'static'/'index.html').read_text(encoding='utf8')

class Login(BaseModel):password:str
@app.post('/api/login')
def login(payload:Login,request:Request):
    if not secrets.compare_digest(payload.password,PWD):raise HTTPException(401,'Credenciais inválidas')
    request.session.clear();request.session['auth']=True;request.session['csrf']=secrets.token_urlsafe(24)
    return {'ok':True,'csrf':request.session['csrf']}
@app.post('/api/logout')
def logout(request:Request):
    guard(request,True);request.session.clear();return {'ok':True}
@app.get('/api/session')
def session(request:Request):
    return {'auth':bool(request.session.get('auth')),'csrf':request.session.get('csrf','') if request.session.get('auth') else ''}
@app.get('/api/dashboard')
def dashboard(request:Request):
    guard(request)
    with db() as c:
        total=c.execute('SELECT count(*) n FROM conversations').fetchone()['n']
        handoffs=c.execute("SELECT count(*) n FROM conversations WHERE status='human'").fetchone()['n']
        active=c.execute("SELECT count(*) n FROM conversations WHERE status='bot'").fetchone()['n']
        faq=c.execute('SELECT count(*) n FROM faqs WHERE active=1').fetchone()['n']
        recent=[dict(x) for x in c.execute('SELECT id,contact,kind,goal,status,updated_at FROM conversations ORDER BY updated_at DESC LIMIT 8')]
    return {'total':total,'handoffs':handoffs,'active':active,'faqs':faq,'recent':recent,'mode':'DEMONSTRAÇÃO / SEM WHATSAPP'}
@app.get('/api/faqs')
def faqs(request:Request):
    guard(request)
    with db() as c:return [dict(x) for x in c.execute('SELECT * FROM faqs ORDER BY id')]
class FAQ(BaseModel):question:str=Field(min_length=3,max_length=250);answer:str=Field(min_length=3,max_length=2000)
@app.post('/api/faqs')
def add_faq(item:FAQ,request:Request):
    guard(request,True)
    with db() as c:
        cur=c.execute('INSERT INTO faqs(question,answer) VALUES(?,?)',(item.question.strip(),item.answer.strip()))
        return {'id':cur.lastrowid}
@app.delete('/api/faqs/{faq_id}')
def delete_faq(faq_id:int,request:Request):
    guard(request,True)
    with db() as c:c.execute('DELETE FROM faqs WHERE id=?',(faq_id,))
    return {'ok':True}
@app.get('/api/conversations')
def conversations(request:Request):
    guard(request)
    with db() as c:return [dict(x) for x in c.execute('SELECT id,contact,kind,goal,timing,company,status,updated_at FROM conversations ORDER BY updated_at DESC LIMIT 100')]
@app.get('/api/conversations/{cid}')
def conversation(cid:int,request:Request):
    guard(request)
    with db() as c:
        row=c.execute('SELECT * FROM conversations WHERE id=?',(cid,)).fetchone()
        if not row:raise HTTPException(404,'Conversa inexistente')
        return output(row,c)

INITIAL='Olá! 👋 Sou o assistente virtual da RISE PDF. Ajudamos empresas a desenvolver websites com estratégia e objetivos de negócio. O que procura?\n\n1 — Website novo\n2 — Renovar website\n3 — Loja online\n4 — Esclarecer dúvidas\n5 — Falar com a equipa'
QUESTIONS={1:'Qual é o principal objetivo do projeto? (ex.: apresentar a empresa, captar contactos ou vender online)',2:'Quando gostaria de avançar? (em breve, 1 a 3 meses ou ainda está a avaliar)',3:'Qual é o nome da empresa ou projeto?',4:'Qual é o seu nome?',5:'Há algum detalhe importante que queira acrescentar? (Pode responder «não».)'}
HANDOFF='Obrigado! Vou encaminhar o seu pedido para a equipa RISE PDF. O atendimento humano será feito assim que houver disponibilidade.'

def addmsg(c,cid,role,body):c.execute('INSERT INTO messages(conversation_id,role,body,created_at) VALUES(?,?,?,?)',(cid,role,body,int(time.time())))

@app.post('/api/conversations')
def create_conversation(request:Request):
    guard(request,True)
    now=int(time.time())
    with db() as c:
        cur=c.execute('INSERT INTO conversations(created_at,updated_at) VALUES(?,?)',(now,now))
        cid=cur.lastrowid;addmsg(c,cid,'assistant',INITIAL)
    return {'id':cid,'reply':INITIAL}

class Message(BaseModel):text:str=Field(min_length=1,max_length=2000)
@app.post('/api/conversations/{cid}/message')
def send_message(cid:int,payload:Message,request:Request):
    guard(request,True)
    body=payload.text.strip()
    if not body:raise HTTPException(400,'Mensagem vazia')
    with db() as c:
        row=c.execute('SELECT * FROM conversations WHERE id=?',(cid,)).fetchone()
        if not row:raise HTTPException(404,'Conversa inexistente')
        addmsg(c,cid,'visitor',body)
        stage=row['stage'];status=row['status'];lower=body.lower()
        if status=='human': reply='A conversa está atribuída à equipa. O assistente permanece em pausa.'
        elif any(x in lower for x in ('humano','pessoa','equipa','proposta','orçamento','reunião')):
            reply=HANDOFF;c.execute('UPDATE conversations SET status=? WHERE id=?',('human',cid))
        elif stage==0:
            first=lower.strip()[:1]
            types={'1':'Website novo','2':'Renovação','3':'Loja online','4':'Dúvidas','5':'Atendimento humano'}
            kind=types.get(first) or ('Loja online' if 'loja' in lower else 'Renovação' if 'renov' in lower else 'Website novo' if 'website' in lower or 'site' in lower else None)
            if kind=='Atendimento humano':reply=HANDOFF;c.execute('UPDATE conversations SET status=? WHERE id=?',('human',cid))
            elif kind=='Dúvidas':
                reply='Claro. Escreva a sua dúvida sobre websites ou lojas online. Também pode responder «website novo» quando quiser falar do seu projeto.'
                c.execute('UPDATE conversations SET stage=6,kind=? WHERE id=?',(kind,cid))
            elif kind:
                c.execute('UPDATE conversations SET kind=?,stage=1 WHERE id=?',(kind,cid));reply=QUESTIONS[1]
            else:reply='Para começar, indique uma opção de 1 a 5, ou descreva o projeto que procura.'
        elif stage==6:
            if 'website' in lower and 'novo' in lower:
                c.execute("UPDATE conversations SET kind='Website novo',stage=1 WHERE id=?",(cid,));reply=QUESTIONS[1]
            else:
                words=set(re.findall(r'\w+',lower))
                best=None;best_score=0
                for faq in c.execute('SELECT * FROM faqs WHERE active=1'):
                    score=len(words & set(re.findall(r'\w+',faq['question'].lower())))
                    if score>best_score:best_score=score;best=faq
                reply=(best['answer']+'\n\nPosso esclarecer outra questão ou encaminhar para a equipa.' if best and best_score>=2 else 'Não tenho informação validada suficiente sobre essa questão. Posso encaminhar para a equipa RISE PDF?')
        elif stage in (1,2,3,4,5):
            field={1:'goal',2:'timing',3:'company',4:'contact',5:'details'}[stage]
            c.execute(f'UPDATE conversations SET {field}=?,stage=? WHERE id=?',(body,stage+1,cid))
            if stage==5:
                c.execute("UPDATE conversations SET status='human' WHERE id=?",(cid,));reply='Obrigado pelas informações! O seu pedido ficou registado nesta demonstração. A equipa poderá agora avaliar o briefing e assumir a conversa.'
            else:reply=QUESTIONS[stage+1]
        else:reply='Obrigado. A equipa poderá dar seguimento ao seu projeto.'
        addmsg(c,cid,'assistant',reply)
        c.execute('UPDATE conversations SET updated_at=? WHERE id=?',(int(time.time()),cid))
    return {'reply':reply}
@app.post('/api/conversations/{cid}/handoff')
def handoff(cid:int,request:Request):
    guard(request,True)
    with db() as c:
        if not c.execute('SELECT id FROM conversations WHERE id=?',(cid,)).fetchone():raise HTTPException(404)
        c.execute("UPDATE conversations SET status='human',updated_at=? WHERE id=?",(int(time.time()),cid))
        addmsg(c,cid,'assistant',HANDOFF)
    return {'ok':True}
@app.get('/api/integration')
def integration(request:Request):
    guard(request)
    return {'chatwoot_url':os.getenv('CHATWOOT_URL',''),'account_configured':bool(os.getenv('CHATWOOT_ACCOUNT_ID')),'token_configured':bool(os.getenv('CHATWOOT_API_TOKEN')),'ai_configured':bool(os.getenv('OPENAI_API_KEY')),'whatsapp_connected':False,'webhooks_connected':False}
@app.get('/health')
def health():return {'status':'ok'}

# --- RISE SmartChat v0.2: extensão Chatwoot (isolada do simulador) ---
import hmac
import hashlib
from chatwoot_bridge import chatwoot_get, chatwoot_post, settings as chatwoot_settings, verify_webhook
from ai_draft import draft as generate_draft

with db() as c:
    c.executescript('''
    CREATE TABLE IF NOT EXISTS chatwoot_events (delivery_id TEXT PRIMARY KEY, event TEXT NOT NULL, received_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS chatwoot_threads (
      conversation_id INTEGER PRIMARY KEY, contact TEXT NOT NULL DEFAULT 'Visitante',
      inbox_id INTEGER, last_preview TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'open',
      ai_paused INTEGER NOT NULL DEFAULT 1, updated_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS activity_log (
      id INTEGER PRIMARY KEY, action TEXT NOT NULL, conversation_id INTEGER,
      created_at INTEGER NOT NULL
    );
    ''')

@app.get('/api/chatwoot/threads')
async def chatwoot_threads(request: Request):
    guard(request)
    remote = await chatwoot_get('conversations?status=all&page=1')
    entries = remote.get('data',{}).get('payload',[]) if isinstance(remote,dict) else []
    if not isinstance(entries,list): entries=[]
    with db() as c:
        flags = {int(row['conversation_id']):bool(row['ai_paused']) for row in c.execute('SELECT conversation_id,ai_paused FROM chatwoot_threads')}
    return [{'id':int(x['id']), 'status':str(x.get('status') or 'open'),
      'contact':str((x.get('meta') or {}).get('sender',{}).get('name') or 'Contacto'),
      'unread_count':int(x.get('unread_count') or 0),
      'ai_paused':flags.get(int(x['id']),True)} for x in entries[:100] if isinstance(x,dict) and isinstance(x.get('id'),int)]

@app.get('/api/chatwoot/threads/{cid}/messages')
async def chatwoot_messages(cid:int,request:Request):
    guard(request)
    if cid<1:raise HTTPException(400,'ID inválido')
    raw=await chatwoot_get(f'conversations/{cid}/messages')
    items = raw.get('payload',[]) if isinstance(raw,dict) else []
    if not isinstance(items,list):items=[]
    return [{'id':x.get('id'),'content':str(x.get('content') or '')[:3000],
      'message_type':x.get('message_type'), 'private':bool(x.get('private',False)),
      'created_at':x.get('created_at')} for x in items[-80:] if isinstance(x,dict)]

class AgentReply(BaseModel):
    content:str=Field(min_length=1,max_length=3000)
    private:bool=False

@app.post('/api/chatwoot/threads/{cid}/reply')
async def chatwoot_human_reply(cid:int,payload:AgentReply,request:Request):
    guard(request,True)
    if cid<1 or not payload.content.strip():raise HTTPException(400,'Mensagem inválida')
    # Requer clique consciente do operador no botão «Enviar»; nunca é invocado por IA.
    sent=await chatwoot_post(f'conversations/{cid}/messages',{
       'content':payload.content.strip(), 'message_type':'outgoing', 'private':payload.private})
    with db() as c:
        c.execute('INSERT INTO chatwoot_threads(conversation_id,ai_paused,updated_at) VALUES(?,1,?) ON CONFLICT(conversation_id) DO UPDATE SET ai_paused=1,updated_at=excluded.updated_at',(cid,int(time.time())))
        c.execute('INSERT INTO activity_log(action,conversation_id,created_at) VALUES(?,?,?)',('agent_message',cid,int(time.time())))
    return {'ok':True,'message_id':sent.get('id') if isinstance(sent,dict) else None}

class PauseState(BaseModel):
    paused:bool

@app.post('/api/chatwoot/threads/{cid}/pause')
def chatwoot_pause(cid:int,payload:PauseState,request:Request):
    guard(request,True)
    if cid<1:raise HTTPException(400,'ID inválido')
    now=int(time.time())
    with db() as c:
        c.execute('INSERT INTO chatwoot_threads(conversation_id,ai_paused,updated_at) VALUES(?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET ai_paused=excluded.ai_paused,updated_at=excluded.updated_at',(cid,int(payload.paused),now))
        c.execute('INSERT INTO activity_log(action,conversation_id,created_at) VALUES(?,?,?)',('pause_ai' if payload.paused else 'resume_ai',cid,now))
    return {'ok':True,'paused':payload.paused,'note':'Estado armazenado. Não existe resposta automática ativa nesta versão.'}

class DraftRequest(BaseModel):
    question:str=Field(min_length=3,max_length=1200)

@app.post('/api/ai/draft')
async def ai_draft(payload:DraftRequest,request:Request):
    guard(request,True)
    with db() as c:
        faqs=[(r['question'],r['answer']) for r in c.execute('SELECT question,answer FROM faqs WHERE active=1 LIMIT 60')]
    reply=await generate_draft(payload.question,faqs)
    return {'draft':reply,'requires_approval':True,'sent':False}

@app.post('/api/webhooks/chatwoot')
async def chatwoot_webhook(request:Request):
    secret=os.getenv('CHATWOOT_WEBHOOK_SECRET','')
    body=await request.body()
    if not verify_webhook(body,request.headers,secret):
        raise HTTPException(401,'Assinatura do webhook inválida')
    delivery=request.headers.get('x-chatwoot-delivery')
    if not delivery or len(delivery)>150:
        # Compatibilidade com envios sem delivery_id: deduplicação por assinatura e timestamp.
        delivery=hashlib.sha256(request.headers['x-chatwoot-signature'].encode()+body).hexdigest()
    try: payload=json.loads(body)
    except (ValueError,UnicodeError):raise HTTPException(400,'JSON inválido')
    if not isinstance(payload,dict):raise HTTPException(400,'Formato inválido')
    event=str(payload.get('event',''))[:100]
    account=payload.get('account') or {}
    configured=os.getenv('CHATWOOT_ACCOUNT_ID','')
    if str(account.get('id','')) != configured or not configured:
        raise HTTPException(403,'Conta Chatwoot não corresponde à configurada')
    conv=payload.get('conversation') or {}
    if not isinstance(conv,dict):conv={}
    cid=conv.get('id') or (payload.get('id') if event.startswith('conversation_') else None)
    if not isinstance(cid,int) or cid<1:cid=None
    sender=payload.get('sender') or conv.get('meta',{}).get('sender') or {}
    if not isinstance(sender,dict):sender={}
    contact=str(sender.get('name') or 'Contacto')[:150]
    message=str(payload.get('content') or '')[:300]
    now=int(time.time())
    with db() as c:
        try:
            c.execute('INSERT INTO chatwoot_events(delivery_id,event,received_at) VALUES(?,?,?)',(delivery,event,now))
        except sqlite3.IntegrityError:
            return {'ok':True,'duplicate':True}
        if cid is not None:
            c.execute('''INSERT INTO chatwoot_threads(conversation_id,contact,last_preview,updated_at)
              VALUES(?,?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET
              contact=CASE WHEN excluded.contact='Contacto' THEN contact ELSE excluded.contact END,
              last_preview=CASE WHEN excluded.last_preview='' THEN last_preview ELSE excluded.last_preview END,
              updated_at=excluded.updated_at''',(cid,contact,message,now))
            if event=='message_created' and (payload.get('message_type')==1 or payload.get('message_type')=='outgoing') and not payload.get('private'):
                c.execute('UPDATE chatwoot_threads SET ai_paused=1 WHERE conversation_id=?',(cid,))
    return {'ok':True,'automated_reply':False}

@app.get('/api/chatwoot/status')
def chatwoot_status(request:Request):
    guard(request)
    with db() as c:
        events=c.execute('SELECT COUNT(*) n FROM chatwoot_events').fetchone()['n']
        threads=c.execute('SELECT COUNT(*) n FROM chatwoot_threads').fetchone()['n']
    return {'configured':all(os.getenv(x) for x in ('CHATWOOT_URL','CHATWOOT_ACCOUNT_ID','CHATWOOT_API_TOKEN')),
       'signed_webhook_ready':bool(os.getenv('CHATWOOT_WEBHOOK_SECRET')),
       'events_received':events,'cached_threads':threads,'ai_drafts_ready':bool(os.getenv('OPENAI_API_KEY')),
       'automatic_sending':False}
