"""
Import massif du registre israélien SANS enrichissement IA.
Objectif : 500 000 sociétés en base en 30 minutes.
Enrichissement IA ensuite, à la demande.
"""
import requests
import sqlite3
import json
import time
from pathlib import Path

DB_PATH = Path(__file__).parent / "helios_data" / "helios.db"
CKAN_URL = "https://data.gov.il/api/3/action/datastore_search"
RESOURCE_ID = "f004176c-b85f-4542-8901-7b3176f9a054"

PAGE_SIZE = 1000   # Le max que CKAN accepte
TOTAL_TARGET = 100000   # Commence par 100K, on verra après

def ensure_schema(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS companies (
        company_number TEXT PRIMARY KEY,
        name_he TEXT, name_en TEXT,
        status_en TEXT, type_en TEXT,
        address_he TEXT, address_en TEXT,
        sector TEXT, context TEXT, risk_flags TEXT,
        name_root TEXT, address_signature TEXT,
        enrichment_status TEXT DEFAULT 'raw',
        enriched_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_name_en ON companies(name_en);
    CREATE INDEX IF NOT EXISTS idx_name_he ON companies(name_he);
    CREATE INDEX IF NOT EXISTS idx_number ON companies(company_number);
    """)

def normalize_hebrew(text):
    if not text: return ""
    import re
    text = re.sub(r'[\u0591-\u05C7]', '', str(text))
    for f, r in {'ך':'כ','ם':'מ','ן':'נ','ף':'פ','ץ':'צ'}.items():
        text = text.replace(f, r)
    return " ".join(text.split())

def get_field(row, *keys):
    for k in keys:
        v = row.get(k)
        if v is not None:
            return str(v).strip()
    return ""

def main():
    print("=" * 60)
    print(f"IMPORT MASSIF — Objectif : {TOTAL_TARGET} sociétés")
    print("=" * 60)

    conn = sqlite3.connect(DB_PATH)
    ensure_schema(conn)

    # Vérifier le total
    existing = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    print(f"Base actuelle : {existing} sociétés")

    offset = 0
    imported = 0
    started = time.time()

    try:
        while imported < TOTAL_TARGET:
            batch_size = min(PAGE_SIZE, TOTAL_TARGET - imported)
            print(f"\n→ Offset {offset} — récupération de {batch_size} sociétés...")

            params = {
                "resource_id": RESOURCE_ID,
                "limit": batch_size,
                "offset": offset,
                "sort": "_id desc",
            }

            try:
                r = requests.get(CKAN_URL, params=params, timeout=60)
                r.raise_for_status()
                records = r.json().get("result", {}).get("records", [])
            except Exception as e:
                print(f"  ⚠️ Erreur : {e} — retry dans 5s")
                time.sleep(5)
                continue

            if not records:
                print("  ✓ Fin des données CKAN")
                break

            # Insertion en batch
            rows = []
            for rec in records:
                nom_he = get_field(rec, "שם חברה", "שם_חברה")
                comp_num = get_field(rec, "מספר חברה", "מספר_חברה")
                if not comp_num or not nom_he:
                    continue

                rue = get_field(rec, "שם רחוב", "שם_רחוב")
                num = get_field(rec, "מספר בית", "מספר_בית")
                ville = get_field(rec, "שם עיר", "שם_עיר")
                addr = f"{rue} {num}, {ville}".strip().strip(",")

                rows.append((
                    comp_num,
                    nom_he,
                    None,          # name_en (sera rempli plus tard)
                    get_field(rec, "סטטוס חברה", "סטטוס_חברה"),
                    get_field(rec, "סוג תאגיד", "סוג_תאגיד"),
                    addr,
                    None,          # address_en
                    None,          # sector
                    None,          # context
                    "[]",          # risk_flags
                    None,          # name_root
                    None,          # address_signature
                    "raw",
                    None
                ))

            conn.executemany("""
                INSERT OR IGNORE INTO companies
                (company_number, name_he, name_en, status_en, type_en,
                 address_he, address_en, sector, context, risk_flags,
                 name_root, address_signature, enrichment_status, enriched_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, rows)
            conn.commit()

            imported += len(rows)
            offset += batch_size

            elapsed = time.time() - started
            rate = imported / elapsed if elapsed > 0 else 0
            eta = (TOTAL_TARGET - imported) / rate if rate > 0 else 0

            print(f"  ✓ {imported} importées | {rate:.0f}/s | ETA {eta/60:.1f} min")

            time.sleep(0.3)   # courtoisie API

    except KeyboardInterrupt:
        print("\n\n⚠️ Interruption manuelle — sauvegarde du progrès...")

    total = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    print(f"\n{'='*60}")
    print(f"✅ TERMINÉ : {total} sociétés en base")
    print(f"Durée : {(time.time()-started)/60:.1f} minutes")
    print(f"{'='*60}")

    conn.close()

if __name__ == "__main__":
    main()