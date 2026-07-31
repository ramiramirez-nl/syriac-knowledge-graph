"""Run the complete data refresh pipeline with backup and rollback.

Usage:
    uv run scripts/update_data.py
    uv run scripts/update_data.py --skip-fetch

The current SQLite database is backed up before any mutation. If fetching,
cleanup, analysis, duplicate detection, export, or validation fails, both the
database and JSON export are restored automatically.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "syriac.db"
JSON_PATH = ROOT / "site" / "data.json"
BACKUP_DIR = ROOT / "data" / "backups"


def run_script(name: str, *args: str) -> None:
    command = [sys.executable, str(ROOT / "scripts" / name), *args]
    print(f"\n==> {' '.join(command[1:])}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def sanitize_database() -> None:
    """Remove invalid edges and authors orphaned by refreshed metadata."""
    with sqlite3.connect(DB_PATH) as conn:
        self_citations = conn.execute(
            "DELETE FROM citations WHERE citing_work_id = cited_work_id"
        ).rowcount
        self_references = conn.execute(
            "DELETE FROM work_references WHERE work_id = referenced_work_id"
        ).rowcount
        orphan_authors = conn.execute(
            "DELETE FROM authors WHERE id NOT IN (SELECT DISTINCT author_id FROM authorship)"
        ).rowcount
        conn.commit()
    print(
        f"Sanitized database: {self_citations} self-citation(s), "
        f"{self_references} self-reference(s), {orphan_authors} orphan author(s) removed."
    )


def restore(backup_db: Path, backup_json: Path | None) -> None:
    shutil.copy2(backup_db, DB_PATH)
    if backup_json and backup_json.exists():
        shutil.copy2(backup_json, JSON_PATH)
    print("Previous database and export restored.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely refresh and rebuild all project data.")
    parser.add_argument("--skip-fetch", action="store_true", help="Rebuild from the current database without calling OpenAlex")
    parser.add_argument("--keep-backups", type=int, default=5, help="Number of dated backup sets to retain (default: 5)")
    args = parser.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")
    if args.keep_backups < 1:
        parser.error("--keep-backups must be at least 1")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_db = BACKUP_DIR / f"syriac-{stamp}.db"
    backup_json = BACKUP_DIR / f"data-{stamp}.json" if JSON_PATH.exists() else None
    shutil.copy2(DB_PATH, backup_db)
    if backup_json:
        shutil.copy2(JSON_PATH, backup_json)
    print(f"Backup created: {backup_db}")

    try:
        if not args.skip_fetch:
            run_script("fetch_openalex.py")
        run_script("remove_reviews.py")
        sanitize_database()
        run_script("compute_analysis.py")
        run_script("find_duplicates.py", "--limit", "0")
        run_script("export_json.py")
        run_script("check_data.py")
    except (subprocess.CalledProcessError, OSError, sqlite3.Error) as exc:
        print(f"\nUpdate failed: {exc}")
        restore(backup_db, backup_json)
        raise SystemExit(1) from exc

    backups = sorted(BACKUP_DIR.glob("syriac-*.db"), reverse=True)
    for old_db in backups[args.keep_backups:]:
        suffix = old_db.stem.removeprefix("syriac-")
        old_json = BACKUP_DIR / f"data-{suffix}.json"
        old_db.unlink(missing_ok=True)
        old_json.unlink(missing_ok=True)

    print("\nUpdate completed successfully.")
    print(f"Rollback backup retained at {backup_db}")


if __name__ == "__main__":
    main()
