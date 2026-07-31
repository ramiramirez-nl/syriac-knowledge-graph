import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "syriac.db"

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("Creating manuscript_details table...")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS manuscript_details (
        work_id TEXT PRIMARY KEY REFERENCES works(id),
        language TEXT,
        date_composed TEXT,
        archive_location TEXT,
        shelfmark TEXT,
        incipit TEXT
    )
    """)
    
    conn.commit()
    conn.close()
    print("Migration complete.")

if __name__ == "__main__":
    migrate()
