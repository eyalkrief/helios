
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
