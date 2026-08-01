"""Create/upgrade the notifications table.

Idempotent: safe to re-run. Beyond the original columns this adds the metadata
the notification generator needs:

  kind        — 'new_work' | 'collaboration' | 'contribution' (what produced it)
  dedupe_key  — stable identity of the *event*, e.g. 'new_work:W123:A456'.
                A UNIQUE index on it lets the generator use INSERT OR IGNORE and
                stay idempotent, so re-running it never spams the same user.
  link        — optional deep link into the site (e.g. '#work=W123')

Usage:
    uv run scripts/migrate_notifications.py
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "syriac.db"

NEW_COLUMNS = {
    "kind": "TEXT DEFAULT 'general'",
    "dedupe_key": "TEXT",
    "link": "TEXT",
}


def migrate(db_path: Path = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            message TEXT NOT NULL,
            is_read INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    existing = {row[1] for row in cursor.execute("PRAGMA table_info(notifications)")}
    for column, definition in NEW_COLUMNS.items():
        if column not in existing:
            print(f"Adding {column} column to notifications...")
            cursor.execute(f"ALTER TABLE notifications ADD COLUMN {column} {definition}")

    # Partial index: rows created before this migration have a NULL dedupe_key
    # and must not collide with each other.
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_notifications_dedupe
        ON notifications (user_id, dedupe_key)
        WHERE dedupe_key IS NOT NULL
        """
    )

    conn.commit()
    conn.close()
    print("Migration complete.")


if __name__ == "__main__":
    migrate()
