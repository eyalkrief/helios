from pathlib import Path
ROOT = Path(__file__).parent
(ROOT / "templates").mkdir(exist_ok=True)
(ROOT / "static").mkdir(exist_ok=True)
(ROOT / "helios_data").mkdir(exist_ok=True)

FILES = {}

FILES["requirements.txt"] = """Flask==3.0.0
requests==2.31.0
python-dotenv==1.0.0
openai==1.12.0
openpyxl==3.1.2
python-docx==1.1.0
reportlab==4.0.9
gunicorn==21.2.0
psycopg2-binary==2.9.9
Flask-SQLAlchemy==3.1.1
"""

FILES["runtime.txt"] = "python-3.11.9\n"
FILES["Procfile"] = "web: gunicorn app:app\n"
FILES[".gitignore"] = """venv/
env/
.env
*.db
helios_data/
__pycache__/
*.pyc
*.log
.vscode/
.idea/
"""

FILES[".env.example"] = """SECRET_KEY=change-me
GOOGLE_CLIENT_ID=xxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=xxx
GOOGLE_REDIRECT_URI=https://helios-app.onrender.com/auth/callback
DEEPSEEK_API_KEY=xxx
"""

FILES["database.py"] = '''
import sqlite3, secrets
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent / "helios_data" / "helios.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    google_id TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    name TEXT, picture TEXT,
    plan TEXT DEFAULT 'free',
    api_key TEXT UNIQUE,
    created_at TEXT NOT NULL,
    last_login_at TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    session_token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS usage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    endpoint TEXT NOT NULL,
    timestamp TEXT NOT NULL
);
"""

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_saas_schema():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        conn.executescript(SCHEMA)

def upsert_user(google_id, email, name, picture):
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        ex = conn.execute("SELECT * FROM users WHERE google_id=?", (google_id,)).fetchone()
        if ex:
            conn.execute("UPDATE users SET email=?,name=?,picture=?,last_login_at=? WHERE user_id=?",
                         (email,name,picture,now,ex["user_id"]))
            uid = ex["user_id"]
        else:
            key = "helios_" + secrets.token_urlsafe(32)
            cur = conn.execute("INSERT INTO users (google_id,email,name,picture,api_key,created_at,last_login_at) VALUES (?,?,?,?,?,?,?)",
                               (google_id,email,name,picture,key,now,now))
            uid = cur.lastrowid
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        return dict(row)

def get_user_by_session(token):
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        row = conn.execute("SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.user_id WHERE s.session_token=? AND s.expires_at>?",
                           (token,now)).fetchone()
        return dict(row) if row else None

def get_user_by_api_key(k):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE api_key=?", (k,)).fetchone()
        return dict(row) if row else None

def create_session(uid, days=30):
    tok = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=days)
    with get_db() as conn:
        conn.execute("INSERT INTO sessions VALUES (?,?,?,?)", (tok,uid,now.isoformat(),exp.isoformat()))
    return tok

def delete_session(t):
    with get_db() as conn:
        conn.execute("DELETE FROM sessions WHERE session_token=?", (t,))

def log_usage(uid, ep):
    with get_db() as conn:
        conn.execute("INSERT INTO usage_log (user_id,endpoint,timestamp) VALUES (?,?,?)",
                     (uid,ep,datetime.now(timezone.utc).isoformat()))

def get_usage_today(uid):
    d = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with get_db() as conn:
        r = conn.execute("SELECT COUNT(*) FROM usage_log WHERE user_id=? AND timestamp LIKE ?", (uid, d+"%")).fetchone()
        return r[0] if r else 0
'''

FILES["auth.py"] = '''
import os
from urllib.parse import urlencode
import requests
from flask import request, session
from database import create_session, delete_session, upsert_user

def google_login_url():
    p = {"client_id": os.environ.get("GOOGLE_CLIENT_ID",""),
         "redirect_uri": os.environ.get("GOOGLE_REDIRECT_URI",""),
         "response_type": "code",
         "scope": "openid email profile",
         "access_type": "offline",
         "prompt": "select_account"}
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(p)

def handle_google_callback():
    code = request.args.get("code")
    if not code: return None
    try:
        r = requests.post("https://oauth2.googleapis.com/token", data={
            "code": code,
            "client_id": os.environ.get("GOOGLE_CLIENT_ID"),
            "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET"),
            "redirect_uri": os.environ.get("GOOGLE_REDIRECT_URI"),
            "grant_type": "authorization_code"}, timeout=10)
        if not r.ok: return None
        at = r.json().get("access_token")
        u = requests.get("https://www.googleapis.com/oauth2/v2/userinfo",
                         headers={"Authorization": "Bearer "+at}, timeout=10)
        if not u.ok: return None
        info = u.json()
        user = upsert_user(info["id"], info["email"], info.get("name",""), info.get("picture",""))
        session["helios_token"] = create_session(user["user_id"])
        return user
    except Exception as e:
        print("OAuth error:", e)
        return None

def logout():
    t = session.pop("helios_token", None)
    if t: delete_session(t)
'''

FILES["app.py"] = '''
import json, os
from functools import wraps
from dotenv import load_dotenv
from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for
import auth
from database import get_db, get_usage_today, get_user_by_api_key, get_user_by_session, init_saas_schema, log_usage

load_dotenv()
init_saas_schema()

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")

def current_user():
    if hasattr(g, "_user"): return g._user
    t = session.get("helios_token")
    g._user = get_user_by_session(t) if t else None
    return g._user

def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if not current_user():
            if request.path.startswith("/api/"):
                return jsonify({"success": False, "error": "unauthorized"}), 401
            return redirect(url_for("landing"))
        return f(*a, **k)
    return w

def api_key_or_login(f):
    @wraps(f)
    def w(*a, **k):
        key = request.headers.get("X-API-Key")
        if key:
            u = get_user_by_api_key(key)
            if not u: return jsonify({"success": False, "error": "invalid_key"}), 401
            g._user = u
            return f(*a, **k)
        if current_user(): return f(*a, **k)
        return jsonify({"success": False, "error": "unauthorized"}), 401
    return w

@app.route("/")
def landing():
    if current_user(): return redirect(url_for("dashboard"))
    return render_template("landing.html")

@app.route("/app")
@login_required
def dashboard():
    return render_template("dashboard.html", user=current_user())

@app.route("/auth/login")
def auth_login():
    return redirect(auth.google_login_url())

@app.route("/auth/callback")
def auth_callback():
    u = auth.handle_google_callback()
    return redirect(url_for("dashboard") if u else url_for("landing"))

@app.route("/auth/logout", methods=["POST"])
def auth_logout():
    auth.logout()
    return redirect(url_for("landing"))

@app.route("/api/me")
@login_required
def api_me():
    u = current_user()
    return jsonify({"success": True, "data": {
        "email": u["email"], "name": u["name"], "picture": u["picture"],
        "plan": u["plan"], "api_key": u["api_key"],
        "usage_today": get_usage_today(u["user_id"])}})

@app.route("/api/companies")
@api_key_or_login
def api_companies():
    search = request.args.get("search", "").strip()
    sector = request.args.get("sector", "").strip()
    limit = min(int(request.args.get("limit", 50)), 500)
    offset = int(request.args.get("offset", 0))
    where, params = [], []
    if search:
        where.append("(name_en LIKE ? OR name_he LIKE ? OR company_number LIKE ?)")
        params += ["%"+search+"%"]*3
    if sector:
        where.append("sector=?")
        params.append(sector)
    ws = ("WHERE " + " AND ".join(where)) if where else ""
    try:
        with get_db() as c:
            total = c.execute("SELECT COUNT(*) FROM companies "+ws, params).fetchone()[0]
            rows = c.execute("SELECT * FROM companies "+ws+" ORDER BY company_number DESC LIMIT ? OFFSET ?",
                             params+[limit,offset]).fetchall()
            companies = []
            for r in rows:
                x = dict(r)
                x["risk_flags"] = json.loads(x.get("risk_flags") or "[]")
                x["cluster_ids"] = []
                companies.append(x)
    except Exception:
        companies, total = [], 0
    if hasattr(g, "_user") and g._user:
        log_usage(g._user["user_id"], "companies_search")
    return jsonify({"success": True, "data": companies, "total": total})

@app.route("/api/company/<cn>")
@api_key_or_login
def api_company(cn):
    with get_db() as c:
        r = c.execute("SELECT * FROM companies WHERE company_number=?", (cn,)).fetchone()
        if not r: return jsonify({"success": False}), 404
        x = dict(r)
        x["risk_flags"] = json.loads(x.get("risk_flags") or "[]")
        x["clusters"] = []
        x["related_companies"] = []
    return jsonify({"success": True, "data": x})

@app.route("/api/clusters")
@api_key_or_login
def api_clusters():
    try:
        with get_db() as c:
            cl = c.execute("SELECT * FROM clusters ORDER BY confidence DESC, size DESC").fetchall()
            res = []
            for x in cl:
                d = dict(x)
                m = c.execute("SELECT c.company_number,c.name_en,c.name_he,c.sector FROM companies c JOIN company_clusters cc ON cc.company_number=c.company_number WHERE cc.cluster_id=?",
                              (d["cluster_id"],)).fetchall()
                d["members"] = [dict(a) for a in m]
                res.append(d)
    except Exception:
        res = []
    return jsonify({"success": True, "data": res})

@app.route("/api/stats")
@api_key_or_login
def api_stats():
    try:
        with get_db() as c:
            total = c.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
            cl = c.execute("SELECT COUNT(*) FROM clusters").fetchone()[0]
            s = c.execute("SELECT sector, COUNT(*) as count FROM companies WHERE sector IS NOT NULL GROUP BY sector ORDER BY count DESC LIMIT 20").fetchall()
    except Exception:
        total, cl, s = 0, 0, []
    return jsonify({"success": True, "data": {"total_companies": total, "total_clusters": cl, "sectors": [dict(r) for r in s]}})

@app.route("/api/health")
def api_health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
'''

FILES["templates/landing.html"] = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Helios</title>
<link rel="stylesheet" href="{{ url_for('static', filename='landing.css') }}">
<link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;800&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
</head><body>
<div class="sun-rays"></div>
<header class="header"><div class="container header-inner"><div class="logo"><span class="logo-text">HELIOS</span></div>
<nav class="nav"><a href="/auth/login" class="btn-nav">Connexion</a></nav></div></header>
<section class="hero"><div class="container">
<div class="hero-badge">Powered by DeepSeek + Open Data israelienne</div>
<h1 class="hero-title">Le premier <em>Company Graph</em><br>d'Israel, genere par IA.</h1>
<p class="hero-subtitle">500 000 societes. 35 000 clusters detectes. Une API unique pour le KYC, la due diligence et la prospection B2B en Israel.</p>
<div class="hero-cta"><a href="/auth/login" class="btn-primary">Commencer avec Google</a></div>
<div class="hero-stats">
<div class="stat"><div class="stat-value">500K+</div><div class="stat-label">Societes</div></div>
<div class="stat"><div class="stat-value">35K+</div><div class="stat-label">Clusters</div></div>
<div class="stat"><div class="stat-value">98%</div><div class="stat-label">Precision</div></div>
</div></div></section>
<footer class="footer"><div class="container"><p>2026 Helios - Le soleil qui eclaire l'economie israelienne.</p></div></footer>
</body></html>"""

FILES["templates/dashboard.html"] = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Helios - Dashboard</title>
<link rel="stylesheet" href="{{ url_for('static', filename='dashboard.css') }}">
<script src="{{ url_for('static', filename='dashboard.js') }}" defer></script>
<link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;800&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
</head><body>
<aside class="sidebar">
<div class="sidebar-logo"><span>HELIOS</span></div>
<nav class="sidebar-nav">
<button class="nav-item active" data-view="companies">Societes</button>
<button class="nav-item" data-view="clusters">Clusters</button>
<button class="nav-item" data-view="stats">Statistiques</button>
<button class="nav-item" data-view="api">API</button>
</nav>
<div class="sidebar-user">
<img src="{{ user.picture }}" alt="" class="user-avatar">
<div class="user-info"><div class="user-name">{{ user.name }}</div><div class="user-email">{{ user.email }}</div></div>
<form action="{{ url_for('auth_logout') }}" method="POST" style="display:inline">
<button type="submit" class="logout-btn">Sortir</button></form>
</div></aside>
<main class="main">
<header class="topbar"><div class="search-wrap"><input type="text" id="search" placeholder="Rechercher..." autocomplete="off"></div></header>
<section class="view active" id="view-companies">
<div class="filters"><select id="sector-filter"><option value="">Tous les secteurs</option></select>
<span class="result-count" id="result-count"></span></div>
<div id="companies-list" class="companies-list"></div><div id="pagination" class="pagination"></div></section>
<section class="view" id="view-clusters"><div id="clusters-list" class="clusters-list"></div></section>
<section class="view" id="view-stats"><div id="stats-content"></div></section>
<section class="view" id="view-api"><div id="api-content"></div></section>
</main>
<div id="modal" class="modal hidden"><div class="modal-inner" id="modal-content"></div></div>
</body></html>"""

FILES["static/landing.css"] = """*{margin:0;padding:0;box-sizing:border-box}
:root{--gold:#FFD966;--night:#0A0E1A;--night-2:#131826;--text:#E8E6DD;--text-dim:#8B8A85}
body{font-family:'Inter',sans-serif;background:var(--night);color:var(--text);line-height:1.6}
.sun-rays{position:fixed;top:-50%;left:50%;transform:translateX(-50%);width:200vw;height:200vh;background:radial-gradient(circle,rgba(255,217,102,0.12) 0%,rgba(255,217,102,0.04) 20%,transparent 60%);pointer-events:none}
.container{max-width:1200px;margin:0 auto;padding:0 2rem;position:relative}
.header{padding:1.5rem 0;border-bottom:1px solid rgba(255,217,102,0.1)}
.header-inner{display:flex;justify-content:space-between;align-items:center}
.logo-text{font-family:'Cinzel',serif;font-weight:800;font-size:1.4rem;letter-spacing:0.3em;color:var(--gold)}
.btn-nav{padding:0.5rem 1.25rem;background:rgba(255,217,102,0.1);border:1px solid rgba(255,217,102,0.3);border-radius:8px;color:var(--gold);text-decoration:none}
.hero{padding:6rem 0;text-align:center}
.hero-badge{display:inline-block;padding:0.4rem 1rem;background:rgba(255,217,102,0.08);border:1px solid rgba(255,217,102,0.2);border-radius:999px;font-size:0.8rem;color:var(--gold);margin-bottom:2rem}
.hero-title{font-family:'Cinzel',serif;font-size:clamp(2.5rem,6vw,4.5rem);line-height:1.1;margin-bottom:1.5rem}
.hero-title em{color:var(--gold)}
.hero-subtitle{font-size:1.15rem;color:var(--text-dim);max-width:640px;margin:0 auto 3rem}
.btn-primary{display:inline-block;padding:0.9rem 1.75rem;background:linear-gradient(135deg,var(--gold),#E8A800);color:var(--night);border-radius:10px;font-weight:600;text-decoration:none}
.hero-stats{display:flex;justify-content:center;gap:4rem;padding-top:3rem;border-top:1px solid rgba(255,217,102,0.1);margin-top:4rem}
.stat-value{font-family:'Cinzel',serif;font-size:2.5rem;color:var(--gold)}
.stat-label{font-size:0.8rem;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.15em}
.footer{padding:3rem 0;text-align:center;color:var(--text-dim);border-top:1px solid rgba(255,217,102,0.1);margin-top:4rem}"""

FILES["static/dashboard.css"] = """*{margin:0;padding:0;box-sizing:border-box}
:root{--gold:#FFD966;--night:#0A0E1A;--night-2:#131826;--night-3:#1C2233;--border:#22283A;--text:#E8E6DD;--text-dim:#8B8A85}
body{font-family:'Inter',sans-serif;background:var(--night);color:var(--text);display:flex;height:100vh;overflow:hidden}
.sidebar{width:240px;background:var(--night-2);border-right:1px solid var(--border);display:flex;flex-direction:column;padding:1.5rem 1rem}
.sidebar-logo{padding:0 0.5rem 1.5rem;border-bottom:1px solid var(--border);margin-bottom:1.5rem;font-family:'Cinzel',serif;font-weight:800;color:var(--gold);letter-spacing:0.25em}
.sidebar-nav{display:flex;flex-direction:column;gap:0.25rem;flex:1}
.nav-item{padding:0.75rem 1rem;background:transparent;border:none;border-radius:8px;color:var(--text-dim);text-align:left;cursor:pointer;font-family:inherit;font-size:0.9rem}
.nav-item:hover,.nav-item.active{background:rgba(255,217,102,0.1);color:var(--gold)}
.sidebar-user{display:flex;align-items:center;gap:0.75rem;padding:0.75rem;background:var(--night-3);border-radius:10px;border:1px solid var(--border)}
.user-avatar{width:32px;height:32px;border-radius:50%}
.user-info{flex:1;min-width:0}
.user-name{font-size:0.85rem;font-weight:600}
.user-email{font-size:0.7rem;color:var(--text-dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.logout-btn{background:none;border:none;color:var(--text-dim);cursor:pointer;font-size:0.75rem}
.main{flex:1;display:flex;flex-direction:column;overflow:hidden}
.topbar{padding:1rem 2rem;background:var(--night-2);border-bottom:1px solid var(--border)}
#search{width:100%;padding:0.65rem 1rem;background:var(--night-3);border:1px solid var(--border);border-radius:8px;color:var(--text);font-family:inherit;outline:none}
.view{display:none;flex:1;overflow-y:auto;padding:2rem}
.view.active{display:block}
.filters{display:flex;gap:1rem;margin-bottom:1.5rem;align-items:center}
#sector-filter{padding:0.55rem 0.9rem;background:var(--night-3);border:1px solid var(--border);border-radius:8px;color:var(--text)}
.result-count{color:var(--text-dim);font-size:0.85rem}
.companies-list{display:flex;flex-direction:column;gap:0.5rem}
.company-row{display:grid;grid-template-columns:2fr 1.5fr 1.5fr 1fr;gap:1rem;padding:1rem 1.25rem;background:var(--night-2);border:1px solid var(--border);border-radius:10px;cursor:pointer}
.company-row:hover{background:var(--night-3);border-color:rgba(255,217,102,0.2)}
.company-name{font-weight:600}
.company-name-he{font-size:0.75rem;color:var(--text-dim)}
.company-sector{font-size:0.85rem;color:var(--gold)}
.pagination{display:flex;gap:0.35rem;justify-content:center;margin-top:2rem;flex-wrap:wrap}
.pagination button{padding:0.4rem 0.75rem;background:var(--night-2);border:1px solid var(--border);border-radius:6px;color:var(--text-dim);cursor:pointer}
.pagination button.active{background:var(--gold);color:var(--night)}
.clusters-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(380px,1fr));gap:1rem}
.cluster-card{background:var(--night-2);border:1px solid var(--border);border-radius:12px;padding:1.5rem}
.cluster-type{font-size:0.7rem;text-transform:uppercase;padding:0.2rem 0.6rem;border-radius:999px;background:rgba(255,217,102,0.1);color:var(--gold)}
.cluster-member{padding:0.4rem 0;font-size:0.85rem;color:var(--text-dim);cursor:pointer}
.cluster-member:hover{color:var(--gold)}
.modal{position:fixed;inset:0;background:rgba(0,0,0,0.75);display:flex;align-items:center;justify-content:center;z-index:1000;padding:2rem}
.modal.hidden{display:none}
.modal-inner{background:var(--night-2);border:1px solid var(--border);border-radius:16px;padding:2rem;max-width:700px;width:100%;max-height:85vh;overflow-y:auto}"""

FILES["static/dashboard.js"] = """const $=s=>document.querySelector(s),$$=s=>document.querySelectorAll(s);
let me=null,currentPage=0;const PAGE_SIZE=50;let currentSearch='',currentSector='';
function escapeHTML(s){if(s==null)return'';return String(s).replace(/[&<>'"]/g,t=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[t]))}
$$('.nav-item').forEach(b=>b.addEventListener('click',()=>{
$$('.nav-item').forEach(x=>x.classList.remove('active'));b.classList.add('active');
const v=b.dataset.view;$$('.view').forEach(x=>x.classList.remove('active'));
$('#view-'+v).classList.add('active');
if(v==='clusters')loadClusters();if(v==='stats')loadStats();if(v==='api')loadApi()}));
async function init(){try{const r=await fetch('/api/me');const d=await r.json();if(d.success)me=d.data;
const s=await fetch('/api/stats');const sd=await s.json();
if(sd.success){const sel=$('#sector-filter');sd.data.sectors.forEach(x=>{const o=document.createElement('option');o.value=x.sector;o.textContent=x.sector+' ('+x.count+')';sel.appendChild(o)})}}catch(e){}
loadCompanies()}
async function loadCompanies(){currentSearch=$('#search').value;currentSector=$('#sector-filter').value;currentPage=0;
const url='/api/companies?search='+encodeURIComponent(currentSearch)+'&sector='+encodeURIComponent(currentSector)+'&limit='+PAGE_SIZE+'&offset=0';
const r=await fetch(url);const d=await r.json();
if(d.success){renderCompanies(d.data);renderPagination(d.total);$('#result-count').textContent=d.total+' societes'}}
function renderCompanies(cs){const c=$('#companies-list');
if(!cs.length){c.innerHTML='<div style="text-align:center;padding:3rem;color:var(--text-dim)">Aucune societe</div>';return}
c.innerHTML=cs.map(x=>'<div class="company-row" onclick="showCompany(\\'' + x.company_number + '\\')"><div><div class="company-name">'+escapeHTML(x.name_en)+'</div><div class="company-name-he">'+escapeHTML(x.name_he)+'</div></div><div class="company-sector">'+escapeHTML(x.sector||'-')+'</div><div style="color:var(--text-dim);font-size:0.85rem">'+escapeHTML((x.address_en||'').split(',').pop().trim()||'-')+'</div><div></div></div>').join('')}
function renderPagination(t){const tp=Math.ceil(t/PAGE_SIZE);const c=$('#pagination');if(tp<=1){c.innerHTML='';return}
let h='';for(let i=0;i<Math.min(tp,10);i++)h+='<button onclick="goToPage('+i+')" class="'+(i===currentPage?'active':'')+'">'+(i+1)+'</button>';c.innerHTML=h}
async function goToPage(p){currentPage=p;
const url='/api/companies?search='+encodeURIComponent(currentSearch)+'&sector='+encodeURIComponent(currentSector)+'&limit='+PAGE_SIZE+'&offset='+(p*PAGE_SIZE);
const r=await fetch(url);const d=await r.json();if(d.success){renderCompanies(d.data);renderPagination(d.total)}}
async function showCompany(n){const r=await fetch('/api/company/'+n);const d=await r.json();if(!d.success)return;const c=d.data;
$('#modal-content').innerHTML='<div><button onclick="closeModal()" style="float:right;background:none;border:none;color:var(--text-dim);font-size:1.5rem;cursor:pointer">x</button><h2 style="font-family:Cinzel;color:var(--gold);margin-bottom:1rem">'+escapeHTML(c.name_en)+'</h2><p style="color:var(--text-dim);margin-bottom:1rem">'+escapeHTML(c.name_he)+'</p><p><strong>Secteur:</strong> '+escapeHTML(c.sector)+'</p><p><strong>Statut:</strong> '+escapeHTML(c.status_en)+'</p><p><strong>Adresse:</strong> '+escapeHTML(c.address_en)+'</p></div>';
$('#modal').classList.remove('hidden')}
function closeModal(){$('#modal').classList.add('hidden')}
$('#modal').addEventListener('click',e=>{if(e.target.id==='modal')closeModal()});
async function loadClusters(){const r=await fetch('/api/clusters');const d=await r.json();const c=$('#clusters-list');
if(!d.success||!d.data.length){c.innerHTML='<div style="text-align:center;padding:3rem;color:var(--text-dim)">Aucun cluster</div>';return}
c.innerHTML=d.data.map(cl=>'<div class="cluster-card"><span class="cluster-type">'+cl.cluster_type+'</span><div style="font-family:Cinzel;color:var(--gold);font-size:1.5rem;margin:0.5rem 0">'+escapeHTML(cl.cluster_key)+'</div><div style="font-size:0.8rem;color:var(--text-dim);margin-bottom:1rem">Confiance: '+Math.round(cl.confidence*100)+'% | '+cl.size+' societes</div><div>'+cl.members.map(m=>'<div class="cluster-member" onclick="showCompany(\\'' + m.company_number + '\\')">'+escapeHTML(m.name_en)+'</div>').join('')+'</div></div>').join('')}
async function loadStats(){const r=await fetch('/api/stats');const d=await r.json();if(!d.success)return;const s=d.data;
$('#stats-content').innerHTML='<div style="display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;margin-bottom:2rem"><div style="background:var(--night-2);border:1px solid var(--border);border-radius:12px;padding:2rem"><div style="color:var(--text-dim)">Societes</div><div style="font-family:Cinzel;font-size:3rem;color:var(--text)">'+s.total_companies+'</div></div><div style="background:var(--night-2);border:1px solid var(--border);border-radius:12px;padding:2rem"><div style="color:var(--text-dim)">Clusters</div><div style="font-family:Cinzel;font-size:3rem;color:var(--gold)">'+s.total_clusters+'</div></div></div>'}
async function loadApi(){if(!me)return;
$('#api-content').innerHTML='<div><h2 style="font-family:Cinzel;color:var(--gold)">Votre cle API</h2><code style="display:block;background:var(--night-3);padding:1rem;border-radius:8px;margin:1rem 0;color:var(--gold);word-break:break-all">'+me.api_key+'</code><p style="color:var(--text-dim);font-size:0.9rem">Utilisez cette cle dans le header X-API-Key</p></div>'}
let debounce;$('#search').addEventListener('input',()=>{clearTimeout(debounce);debounce=setTimeout(loadCompanies,400)});
$('#sector-filter').addEventListener('change',loadCompanies);
init();
"""

def main():
    created = []
    for name, content in FILES.items():
        p = ROOT / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        created.append(name)
    print("=" * 60)
    print("  " + str(len(created)) + " FICHIERS CREES")
    print("=" * 60)
    for f in created:
        print("  OK " + f)
    print("=" * 60)
    print()
    print("PROCHAINE ETAPE :")
    print("  git add .")
    print("  git commit -m 'Initial commit'")
    print("  git branch -M main")
    print("  git push -u origin main")
    print()

if __name__ == "__main__":
    main()
