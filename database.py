"""Base de données — SQLite en local, PostgreSQL en prod."""
import os, secrets, sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("NEON_DATABASE_URL")
USE_PG = bool(DATABASE_URL and DATABASE_URL.startswith("postgres"))
DB_PATH = Path(__file__).parent / "helios_data" / "helios.db"

if USE_PG:
    import psycopg

@contextmanager
def get_db():
    if USE_PG:
        conn = psycopg.connect(DATABASE_URL)
        conn.autocommit = False
        yield conn
        conn.commit()
        conn.close()
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

def _q(sql):
    return sql.replace("?", "%s") if USE_PG else sql

def _exec(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(_q(sql), params)
    return cur

def _row(cur, row):
    if row is None: return None
    if USE_PG:
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))
    return dict(row)

def init_saas_schema():
    if not USE_PG: DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    id_type = "SERIAL PRIMARY KEY" if USE_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
    ddl = f"""
    CREATE TABLE IF NOT EXISTS users (
        user_id {id_type}, google_id TEXT UNIQUE NOT NULL, email TEXT UNIQUE NOT NULL,
        name TEXT, picture TEXT, plan TEXT DEFAULT 'free', api_key TEXT UNIQUE,
        created_at TEXT NOT NULL, last_login_at TEXT
    );
    CREATE TABLE IF NOT EXISTS sessions (
        session_token TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
        created_at TEXT NOT NULL, expires_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS usage_log (
        id {id_type}, user_id INTEGER NOT NULL, endpoint TEXT NOT NULL, timestamp TEXT NOT NULL
    );
    """
    with get_db() as conn:
        _exec(conn, ddl)

def upsert_user(google_id, email, name, picture):
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        cur = _exec(conn, "SELECT * FROM users WHERE google_id=?", (google_id,))
        ex = cur.fetchone()
        if ex:
            uid = _row(cur, ex)["user_id"]
            _exec(conn, "UPDATE users SET email=?,name=?,picture=?,last_login_at=? WHERE user_id=?",
                  (email, name, picture, now, uid))
        else:
            key = "helios_" + secrets.token_urlsafe(32)
            _exec(conn, "INSERT INTO users (google_id,email,name,picture,api_key,created_at,last_login_at) VALUES (?,?,?,?,?,?,?)",
                  (google_id, email, name, picture, key, now, now))
            cur2 = _exec(conn, "SELECT * FROM users WHERE google_id=?", (google_id,))
            uid = _row(cur2, cur2.fetchone())["user_id"]
        cur3 = _exec(conn, "SELECT * FROM users WHERE user_id=?", (uid,))
        return _row(cur3, cur3.fetchone())

def get_user_by_session(token):
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        cur = _exec(conn, "SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.user_id WHERE s.session_token=? AND s.expires_at>?",
                    (token, now))
        return _row(cur, cur.fetchone())

def get_user_by_api_key(k):
    with get_db() as conn:
        cur = _exec(conn, "SELECT * FROM users WHERE api_key=?", (k,))
        return _row(cur, cur.fetchone())

def create_session(uid, days=30):
    t = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=days)
    with get_db() as conn:
        _exec(conn, "INSERT INTO sessions (session_token,user_id,created_at,expires_at) VALUES (?,?,?,?)",
              (t, uid, now.isoformat(), exp.isoformat()))
    return t

def delete_session(t):
    with get_db() as conn:
        _exec(conn, "DELETE FROM sessions WHERE session_token=?", (t,))

def log_usage(uid, ep):
    with get_db() as conn:
        _exec(conn, "INSERT INTO usage_log (user_id,endpoint,timestamp) VALUES (?,?,?)",
              (uid, ep, datetime.now(timezone.utc).isoformat()))

def get_usage_today(uid):
    d = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with get_db() as conn:
        cur = _exec(conn, "SELECT COUNT(*) FROM usage_log WHERE user_id=? AND timestamp LIKE ?", (uid, d+"%"))
        row = cur.fetchone()
        return row[0] if row else 0