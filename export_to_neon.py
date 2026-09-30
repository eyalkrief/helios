"""Exporte SQLite local → PostgreSQL Neon."""
import sqlite3, psycopg2, os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
DB_LOCAL = Path(__file__).parent / "helios_data" / "helios.db"
NEON_URL = os.environ.get("NEON_DATABASE_URL")
if not NEON_URL:
    print("Ajoute NEON_DATABASE_URL=... dans .env"); exit(1)

pg = psycopg2.connect(NEON_URL); pg.autocommit = False; cur = pg.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS companies (
    company_number TEXT PRIMARY KEY,
    name_he TEXT, name_en TEXT, status_en TEXT, type_en TEXT,
    address_he TEXT, address_en TEXT, sector TEXT, context TEXT,
    risk_flags TEXT DEFAULT '[]', name_root TEXT, address_signature TEXT,
    enrichment_status TEXT DEFAULT 'raw', enriched_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_name_he ON companies(name_he);
""")
pg.commit(); print("✓ Table créée")

conn = sqlite3.connect(DB_LOCAL); conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT * FROM companies").fetchall()
print(f"Transfert de {len(rows)} sociétés...")

batch = []
for i, r in enumerate(rows, 1):
    batch.append(tuple(r))
    if len(batch) >= 500:
        cur.executemany("INSERT INTO companies VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (company_number) DO NOTHING", batch)
        pg.commit(); batch = []
        if i % 5000 == 0: print(f"  {i}/{len(rows)}")
if batch:
    cur.executemany("INSERT INTO companies VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (company_number) DO NOTHING", batch)
    pg.commit()
print(f"✅ {len(rows)} sociétés dans Neon")