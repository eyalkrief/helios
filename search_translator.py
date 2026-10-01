"""
Moteur de traduction de la barre de recherche.
Traduit les termes EN/FR → HE et retourne une liste de variantes.
"""
import json
import os
from datetime import datetime

from database import get_db, _exec, _row


# ═══════════════════════════════════════════════════════════════
# DICTIONNAIRE DES VILLES ISRAÉLIENNES
# ═══════════════════════════════════════════════════════════════

CITIES = {
    # Grandes villes
    "tel aviv": "תל אביב",
    "tel aviv-yafo": "תל אביב - יפו",
    "tel aviv yafo": "תל אביב - יפו",
    "jaffa": "יפו",
    "jerusalem": "ירושלים",
    "haifa": "חיפה",
    "beer sheva": "באר שבע",
    "be'er sheva": "באר שבע",
    "beersheba": "באר שבע",
    "netanya": "נתניה",
    "rishon lezion": "ראשון לציון",
    "rishon le zion": "ראשון לציון",
    "petah tikva": "פתח תקווה",
    "petach tikva": "פתח תקווה",
    "ashdod": "אשדוד",
    "holon": "חולון",
    "bnei brak": "בני ברק",
    "ramat gan": "רמת גן",
    "rehovot": "רחובות",
    "bat yam": "בת ים",
    "kfar saba": "כפר סבא",
    "herzliya": "הרצליה",
    "hadera": "חדרה",
    "modiin": "מודיעין",
    "ashkelon": "אשקלון",
    "nazareth": "נצרת",
    "lod": "לוד",
    "ramla": "רמלה",
    "raanana": "רעננה",
    "ra'anana": "רעננה",
    "givatayim": "גבעתיים",
    "kiryat gat": "קריית גת",
    "kiryat ata": "קריית אתא",
    "kiryat bialik": "קריית ביאליק",
    "kiryat motzkin": "קריית מוצקין",
    "kiryat yam": "קריית ים",
    "kiryat shmona": "קריית שמונה",
    "nahariya": "נהריה",
    "acre": "עכו",
    "akko": "עכו",
    "afula": "עפולה",
    "tiberias": "טבריה",
    "safed": "צפת",
    "tzfat": "צפת",
    "eilat": "אילת",
    "dimona": "דימונה",
    "arad": "ערד",
    "ofakim": "אופקים",
    "netivot": "נתיבות",
    "sderot": "שדרות",
    "yavne": "יבנה",
    "ness ziona": "נס ציונה",
    "rosh haayin": "ראש העין",
    "rosh ha'ayin": "ראש העין",
    "hod hasharon": "הוד השרון",
    "kfar yona": "כפר יונה",
    "tayibe": "טייבה",
    "tira": "טירה",
    "sakhnin": "סח'נין",
    "shefa-amr": "שפרעם",
    "shefa amr": "שפרעם",
    "umm al-fahm": "אום אל-פחם",
    "umm al fahm": "אום אל-פחם",
    "baqa al-gharbiyye": "באקה אל-גרביה",
    "nazareth illit": "נצרת עילית",
    "nof hagalil": "נוף הגליל",
    "maale adumim": "מעלה אדומים",
    "ma'ale adumim": "מעלה אדומים",
    "modiin illit": "מודיעין עילית",
    "beitar illit": "ביתר עילית",
    "bet shemesh": "בית שמש",
    "beit shemesh": "בית שמש",
    "givataim": "גבעתיים",
    "givat shmuel": "גבעת שמואל",
    "or yehuda": "אור יהודה",
    "yehud": "יהוד",
    "kiryat ono": "קריית אונו",
    "ganei tikva": "גני תקווה",
    "elad": "אלעד",
    "shoham": "שוהם",
    # Villes arabes / druzes
    "daliat al-carmel": "דאלית אל-כרמל",
    "daliyat al-karmel": "דאלית אל-כרמל",
    "isifya": "עיסיפיא",
    "kafr qasim": "כפר קאסם",
    "kafr qara": "כפר קרע",
    "rahat": "רהט",
    "kuseife": "כסיפה",
    "arara": "ערערה",
    "baqa": "באקה",
    "jatt": "ג'ת",
    "tamra": "טמרה",
    "yarka": "ירכא",
    "kisra-sumei": "כסרא-סמיע",
    "tuba-zangariyya": "טובא-זנגריה",
}

# Mots-clés communs (types d'activité)
KEYWORDS = {
    # Tech
    "tech": "טכנולוגיות",
    "technology": "טכנולוגיות",
    "software": "תוכנה",
    "startup": "סטארטאפ",
    "ai": "בינה מלאכותית",
    "it": "מחשוב",
    "cyber": "סייבר",
    "fintech": "פינטק",
    "data": "דאטה",
    # Commerce
    "restaurant": "מסעדה",
    "cafe": "קפה",
    "shop": "חנות",
    "store": "חנות",
    "market": "שוק",
    "supermarket": "סופרמרקט",
    "bakery": "מאפייה",
    "pharmacy": "בית מרקחת",
    "hotel": "מלון",
    "bar": "בר",
    "coffee": "קפה",
    "food": "אוכל",
    # Construction / immobilier
    "construction": "בנייה",
    "real estate": "נדלן",
    "building": "בנייה",
    "renovation": "שיפוצים",
    "contractor": "קבלן",
    "developer": "יזם",
    # Services
    "lawyer": "עורך דין",
    "law": "משפטים",
    "accountant": "רואה חשבון",
    "consulting": "ייעוץ",
    "marketing": "שיווק",
    "advertising": "פרסום",
    "design": "עיצוב",
    "transport": "הובלות",
    "logistics": "לוגיסטיקה",
    "plumber": "אינסטלטור",
    "electrician": "חשמלאי",
    "cleaning": "ניקיון",
    "security": "אבטחה",
    "training": "הדרכה",
    # Santé
    "medical": "רפואה",
    "doctor": "רופא",
    "clinic": "מרפאה",
    "dental": "שיניים",
    "hospital": "בית חולים",
    # Industrie
    "manufacturing": "ייצור",
    "factory": "מפעל",
    "industrial": "תעשייה",
    "import": "יבוא",
    "export": "יצוא",
    # Éducation
    "school": "בית ספר",
    "university": "אוניברסיטה",
    "education": "חינוך",
    # Finance
    "bank": "בנק",
    "insurance": "ביטוח",
    "investment": "השקעות",
    "finance": "מימון",
    "fund": "קרן",
    "holding": "אחזקות",
}


# ═══════════════════════════════════════════════════════════════
# CACHE EN BASE
# ═══════════════════════════════════════════════════════════════

def get_cached_translation(term):
    """Cherche une traduction dans le cache."""
    try:
        with get_db() as conn:
            cur = _exec(conn,
                "SELECT term_translated FROM search_translations WHERE term_original = ?",
                (term.lower(),))
            row = cur.fetchone()
            if row:
                # Incrémente le compteur de hits
                try:
                    _exec(conn,
                        "UPDATE search_translations SET hits = hits + 1 WHERE term_original = ?",
                        (term.lower(),))
                except Exception:
                    pass
                # row est un tuple pour psycopg, un Row pour sqlite
                return row[0] if not hasattr(row, "keys") else row["term_translated"]
    except Exception as e:
        print(f"⚠️ Cache lecture échoué : {e}")
    return None


def save_translation(term, translation, source_lang="auto"):
    """Sauvegarde une traduction dans le cache."""
    try:
        now = datetime.now().isoformat()
        with get_db() as conn:
            _exec(conn,
                "INSERT INTO search_translations "
                "(term_original, term_translated, source_lang, hits, created_at) "
                "VALUES (?, ?, ?, 0, ?)",
                (term.lower(), translation, source_lang, now))
    except Exception as e:
        msg = str(e).lower()
        if "unique" not in msg and "duplicate" not in msg:
            print(f"⚠️ Cache sauvegarde échoué : {e}")


# ═══════════════════════════════════════════════════════════════
# TRADUCTION DEEPSEEK (fallback)
# ═══════════════════════════════════════════════════════════════

def translate_with_deepseek(term):
    """Traduit un terme via DeepSeek. Retourne la traduction hébraïque."""
    try:
        from openai import OpenAI
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            return None

        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

        prompt = f"""Traduis ce terme de recherche en HÉBREU pour une recherche d'entreprises israéliennes.

Terme à traduire : "{term}"

Règles :
- Si c'est une ville israélienne, donne le nom hébreu officiel (ex: "Tel Aviv" → "תל אביב")
- Si c'est un type d'activité, donne le mot hébreu courant (ex: "restaurant" → "מסעדה")
- Si c'est un nom propre d'entreprise, translittère-le en hébreu
- Si rien ne correspond, retourne le terme original en anglais

Réponds UNIQUEMENT en JSON strict :
{{"translation": "traduction en hébreu", "confidence": 0.0-1.0}}
"""

        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "Réponds UNIQUEMENT en JSON strict."},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            timeout=10,
        )

        data = json.loads(resp.choices[0].message.content)
        return data.get("translation")

    except Exception as e:
        print(f"⚠️ DeepSeek traduction échouée : {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# FONCTION PRINCIPALE
# ═══════════════════════════════════════════════════════════════

def get_search_variants(term):
    """
    Retourne une liste de variantes à chercher dans la base.
    Stratégie : terme original + traductions EN + HE si possible.

    Exemple :
        "Tel Aviv" → ["Tel Aviv", "תל אביב"]
        "restaurant" → ["restaurant", "מסעדה"]
    """
    if not term or len(term) < 2:
        return [term] if term else []

    term_lower = term.lower().strip()
    variants = [term]  # Toujours le terme original

    # 1. Dictionnaire villes
    if term_lower in CITIES:
        variants.append(CITIES[term_lower])
        return list(dict.fromkeys(variants))  # dédoublonne en gardant l'ordre

    # 2. Dictionnaire mots-clés
    if term_lower in KEYWORDS:
        variants.append(KEYWORDS[term_lower])
        return list(dict.fromkeys(variants))

    # 3. Cache base
    cached = get_cached_translation(term_lower)
    if cached and cached.lower() != term_lower:
        variants.append(cached)
        return list(dict.fromkeys(variants))

    # 4. DeepSeek (1 appel + mise en cache)
    translation = translate_with_deepseek(term)
    if translation and translation.lower() != term_lower:
        variants.append(translation)
        save_translation(term_lower, translation)
        print(f"🌐 Traduit '{term}' → '{translation}' (caché)")

    return list(dict.fromkeys(variants))