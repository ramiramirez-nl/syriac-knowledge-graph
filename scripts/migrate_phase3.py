import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "syriac.db"

def migrate():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if bio and interests exist in authors
    cursor.execute("PRAGMA table_info(authors)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'bio' not in columns:
        print("Adding bio column to authors...")
        cursor.execute("ALTER TABLE authors ADD COLUMN bio TEXT")
        
    if 'interests' not in columns:
        print("Adding interests column to authors...")
        cursor.execute("ALTER TABLE authors ADD COLUMN interests TEXT")

    # Create pending_contributions table
    print("Creating pending_contributions table...")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pending_contributions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER REFERENCES users(id),
        type TEXT NOT NULL,
        payload TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        submitted_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    conn.commit()
    conn.close()
    print("Migration complete.")

if __name__ == "__main__":
    migrate()
