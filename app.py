"""Helios SaaS — Application principale."""
import json
import os
from datetime import datetime
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask, g, jsonify, redirect, render_template,
    request, session, url_for,
)

import auth
from database import (
    _exec, _row,
    get_db, get_usage_today, get_user_by_api_key,
    get_user_by_session, init_saas_schema, log_usage,
)

# ═══════════════════════════════════════════════════════════════
# INIT
# ═══════════════════════════════════════════════════════════════

load_dotenv()
init_saas_schema()

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True


# ═══════════════════════════════════════════════════════════════
# AUTH MIDDLEWARE
# ═══════════════════════════════════════════════════════════════

def current_user():
    if hasattr(g, "_user"):
        return g._user
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
            if not u:
                return jsonify({"success": False, "error": "invalid_key"}), 401
            g._user = u
            return f(*a, **k)
        if current_user():
            return f(*a, **k)
        return jsonify({"success": False, "error": "unauthorized"}), 401
    return w


# ═══════════════════════════════════════════════════════════════
# ENRICHISSEMENT À LA DEMANDE (DeepSeek)
# ═══════════════════════════════════════════════════════════════

def enrich_on_demand(company_number):
    """
    Appelle DeepSeek pour traduire une société non encore enrichie.
    Retourne le dict de la société mise à jour.
    """
    from openai import OpenAI

    # 1. Charge la société
    with get_db() as conn:
        cur = _exec(conn, "SELECT * FROM companies WHERE company_number=?", (company_number,))
        row = cur.fetchone()
        if not row:
            return None
        c = _row(cur, row)

    # 2. Déjà enrichie ? On retourne directement
    if c.get("enrichment_status") == "ok":
        return c

    # 3. Appel DeepSeek
    try:
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            print("⚠️ DEEPSEEK_API_KEY manquante")
            return c

        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

        prompt = f"""Tu es un expert en données d'entreprises israéliennes.
Traduis et enrichis ces données brutes en JSON strict.

Données brutes :
- Nom hébreu : {c.get('name_he', '')}
- Numéro     : {c.get('company_number', '')}
- Statut     : {c.get('status_he_raw', c.get('status_en', ''))}
- Adresse    : {c.get('address_he', '')}

Réponds en JSON avec ces clés exactes :
- "name_en" : traduction anglaise du nom
- "status_en" : traduction anglaise du statut (Active, Dissolved, etc.)
- "type_en" : traduction du type d'entité (si absent, mets "Israeli Private Company")
- "address_en" : traduction anglaise de l'adresse (ou "Not available")
- "sector" : secteur d'activité en anglais (spécifique, ex: "HVAC Installation")
- "context" : une phrase de 15-25 mots en anglais
- "risk_flags" : liste de drapeaux de risque (vide [] si aucun)
"""

        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "Réponds UNIQUEMENT en JSON strict."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            timeout=15,
        )

        enriched = json.loads(resp.choices[0].message.content)

        # 4. Mise à jour en base
        with get_db() as conn:
            _exec(conn, """
                UPDATE companies SET
                    name_en = ?,
                    status_en = ?,
                    type_en = ?,
                    address_en = ?,
                    sector = ?,
                    context = ?,
                    risk_flags = ?,
                    enrichment_status = 'ok',
                    enriched_at = ?
                WHERE company_number = ?
            """, (
                enriched.get("name_en"),
                enriched.get("status_en"),
                enriched.get("type_en"),
                enriched.get("address_en"),
                enriched.get("sector"),
                enriched.get("context"),
                json.dumps(enriched.get("risk_flags", []), ensure_ascii=False),
                datetime.now().isoformat(),
                company_number,
            ))

        # 5. Recharge la ligne mise à jour
        with get_db() as conn:
            cur = _exec(conn, "SELECT * FROM companies WHERE company_number=?", (company_number,))
            c = _row(cur, cur.fetchone())

        print(f"✅ Enrichi : {c.get('name_en')}")
        return c

    except Exception as e:
        print(f"⚠️ Enrichissement échoué pour {company_number} : {e}")
        return c


# ═══════════════════════════════════════════════════════════════
# ROUTES — PAGES
# ═══════════════════════════════════════════════════════════════

@app.route("/")
def landing():
    if current_user():
        return redirect(url_for("dashboard"))
    return render_template("landing.html")


@app.route("/app")
@login_required
def dashboard():
    return render_template("dashboard.html", user=current_user())


# ═══════════════════════════════════════════════════════════════
# ROUTES — AUTH
# ═══════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════
# ROUTES — API
# ═══════════════════════════════════════════════════════════════

@app.route("/api/me")
@login_required
def api_me():
    u = current_user()
    return jsonify({"success": True, "data": {
        "email": u["email"],
        "name": u["name"],
        "picture": u["picture"],
        "plan": u["plan"],
        "api_key": u["api_key"],
        "usage_today": get_usage_today(u["user_id"]),
    }})


@app.route("/api/companies")
@api_key_or_login
def api_companies():
    search = request.args.get("search", "").strip()
    sector = request.args.get("sector", "").strip()
    status = request.args.get("status", "").strip()
    city = request.args.get("city", "").strip()
    number_type = request.args.get("number_type", "").strip()
    limit = min(int(request.args.get("limit", 50)), 500)
    offset = int(request.args.get("offset", 0))

    where, params = [], []

    # ⬇️ RECHERCHE MULTI-LANGUE avec traduction automatique
    if search:
        try:
            from search_translator import get_search_variants
            variants = get_search_variants(search)
        except Exception as e:
            print(f"⚠️ Traduction indisponible : {e}")
            variants = [search]

        # Une sous-clause par variante
        sub_clauses = []
        for v in variants:
            sub_clauses.append(
                "(name_en LIKE ? OR name_he LIKE ? OR company_number LIKE ? "
                "OR address_he LIKE ? OR address_en LIKE ? "
                "OR sector LIKE ? OR context LIKE ?)"
            )
            params += ["%" + v + "%"] * 7

        where.append("(" + " OR ".join(sub_clauses) + ")")
        print(f"🔍 Recherche '{search}' → variantes : {variants}")

    if sector:
        where.append("sector = ?")
        params.append(sector)
    if status:
        where.append("status_en = ?")
        params.append(status)
    if city:
        where.append("city_he = ?")
        params.append(city)
    if number_type == "vintage":
        where.append("LENGTH(company_number) = 9 AND company_number LIKE '51%'")
    elif number_type == "modern":
        where.append("LENGTH(company_number) >= 10 AND company_number LIKE '51%'")
    elif number_type == "foreign":
        where.append("company_number LIKE '56%'")

    ws = ("WHERE " + " AND ".join(where)) if where else ""

    try:
        with get_db() as conn:
            cur = _exec(conn, "SELECT COUNT(*) FROM companies " + ws, params)
            total = cur.fetchone()[0]

            cur2 = _exec(
                conn,
                "SELECT * FROM companies " + ws + " ORDER BY company_number DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            )
            companies = []
            for r in cur2.fetchall():
                x = _row(cur2, r)
                x["risk_flags"] = json.loads(x.get("risk_flags") or "[]")
                x["cluster_ids"] = []
                companies.append(x)
    except Exception as e:
        print(f"Erreur /api/companies : {e}")
        companies, total = [], 0

    if hasattr(g, "_user") and g._user:
        log_usage(g._user["user_id"], "companies_search")

    return jsonify({"success": True, "data": companies, "total": total})


@app.route("/api/translate")
@api_key_or_login
def api_translate():
    """Endpoint debug : retourne les variantes pour un terme."""
    term = request.args.get("term", "").strip()
    if not term:
        return jsonify({"success": False, "error": "term requis"})
    try:
        from search_translator import get_search_variants
        variants = get_search_variants(term)
        return jsonify({"success": True, "data": {"term": term, "variants": variants}})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/filters")
@api_key_or_login
def api_filters():
    """Retourne les valeurs disponibles pour les filtres."""
    try:
        with get_db() as conn:
            cur = _exec(conn,
                "SELECT city_he as value, COUNT(*) as count FROM companies "
                "WHERE city_he IS NOT NULL AND city_he != '' "
                "GROUP BY city_he ORDER BY count DESC LIMIT 20")
            cities = [_row(cur, r) for r in cur.fetchall()]

            cur2 = _exec(conn,
                "SELECT status_en as value, COUNT(*) as count FROM companies "
                "WHERE status_en IS NOT NULL AND status_en != '' "
                "GROUP BY status_en ORDER BY count DESC LIMIT 10")
            statuses = [_row(cur2, r) for r in cur2.fetchall()]

            cur3 = _exec(conn,
                "SELECT sector as value, COUNT(*) as count FROM companies "
                "WHERE sector IS NOT NULL AND sector != '' "
                "GROUP BY sector ORDER BY count DESC LIMIT 30")
            sectors = [_row(cur3, r) for r in cur3.fetchall()]

        return jsonify({"success": True, "data": {
            "cities": cities,
            "statuses": statuses,
            "sectors": sectors,
        }})
    except Exception as e:
        print(f"Erreur /api/filters : {e}")
        return jsonify({"success": True, "data": {"cities": [], "statuses": [], "sectors": []}})


@app.route("/api/company/<cn>")
@api_key_or_login
def api_company(cn):
    c = enrich_on_demand(cn)
    if not c:
        return jsonify({"success": False, "error": "not found"}), 404
    c["risk_flags"] = json.loads(c.get("risk_flags") or "[]")
    c["clusters"] = []
    c["related_companies"] = []
    return jsonify({"success": True, "data": c})


@app.route("/api/company/<cn>/find_contacts", methods=["POST"])
@api_key_or_login
def api_find_contacts(cn):
    """Cherche les coordonnées via Google Places API (officielle)."""
    try:
        from scraper_contacts import find_contacts
    except ImportError:
        return jsonify({
            "success": False,
            "error": "scraper_contacts non installé",
            "data": {"phone": "", "website": "", "email": "", "found": False},
        })

    with get_db() as conn:
        cur = _exec(conn, "SELECT * FROM companies WHERE company_number=?", (cn,))
        row = cur.fetchone()
        if not row:
            return jsonify({"success": False, "error": "not found"}), 404
        c = _row(cur, row)

    name = c.get("name_en") or c.get("name_he", "")
    city = c.get("city_he", "")
    if not city and c.get("address_en"):
        parts = c["address_en"].split(",")
        if len(parts) > 1:
            city = parts[-1].strip()

    contacts = find_contacts(name, city)

    with get_db() as conn:
        _exec(conn, """
            UPDATE companies SET
                phone = ?, website = ?, email = ?
            WHERE company_number = ?
        """, (
            contacts.get("phone", ""),
            contacts.get("website", ""),
            contacts.get("email", ""),
            cn,
        ))

    return jsonify({"success": True, "data": contacts})


@app.route("/api/clusters")
@api_key_or_login
def api_clusters():
    try:
        with get_db() as conn:
            cur = _exec(conn, "SELECT * FROM clusters ORDER BY confidence DESC, size DESC")
            clusters_raw = cur.fetchall()
            res = []
            for x in clusters_raw:
                d = _row(cur, x)
                cur2 = _exec(conn,
                    "SELECT c.company_number, c.name_en, c.name_he, c.sector "
                    "FROM companies c "
                    "JOIN company_clusters cc ON cc.company_number = c.company_number "
                    "WHERE cc.cluster_id = ?",
                    (d["cluster_id"],),
                )
                d["members"] = [_row(cur2, m) for m in cur2.fetchall()]
                res.append(d)
    except Exception as e:
        print(f"Erreur /api/clusters : {e}")
        res = []
    return jsonify({"success": True, "data": res})


@app.route("/api/stats")
@api_key_or_login
def api_stats():
    try:
        with get_db() as conn:
            cur = _exec(conn, "SELECT COUNT(*) FROM companies")
            total = cur.fetchone()[0]

            cur2 = _exec(conn, "SELECT COUNT(*) FROM clusters")
            cl = cur2.fetchone()[0]

            cur3 = _exec(conn,
                "SELECT sector, COUNT(*) as count FROM companies "
                "WHERE sector IS NOT NULL GROUP BY sector ORDER BY count DESC LIMIT 20"
            )
            s = [_row(cur3, r) for r in cur3.fetchall()]
    except Exception as e:
        print(f"Erreur /api/stats : {e}")
        total, cl, s = 0, 0, []

    return jsonify({"success": True, "data": {
        "total_companies": total,
        "total_clusters": cl,
        "sectors": s,
    }})


@app.route("/api/health")
def api_health():
    return jsonify({"status": "ok"})


# ═══════════════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)