
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

from database import _exec, _row  # ajoute en haut

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
        where.append("sector=?"); params.append(sector)
    ws = ("WHERE " + " AND ".join(where)) if where else ""
    try:
        with get_db() as conn:
            cur = _exec(conn, "SELECT COUNT(*) FROM companies "+ws, params)
            total = cur.fetchone()[0]
            cur2 = _exec(conn, "SELECT * FROM companies "+ws+" ORDER BY company_number DESC LIMIT ? OFFSET ?",
                         params+[limit,offset])
            companies = []
            for r in cur2.fetchall():
                x = _row(cur2, r)
                import json as _j
                x["risk_flags"] = _j.loads(x.get("risk_flags") or "[]")
                x["cluster_ids"] = []
                companies.append(x)
    except Exception as e:
        print("Erreur:", e)
        companies, total = [], 0
    if hasattr(g, "_user") and g._user:
        log_usage(g._user["user_id"], "companies_search")
    return jsonify({"success": True, "data": companies, "total": total})

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
