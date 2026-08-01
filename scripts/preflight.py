"""Pre-deployment readiness check.

Answers one question: "if I deploy this right now, what breaks?"

Unlike check_data.py (which validates the corpus) this validates the *runtime*
configuration — secrets, database presence, export freshness, and the security
posture of the settings that only matter once the app is reachable from the
internet.

Exit code 0 means safe to deploy, 1 means at least one blocking problem.

Usage:
    uv run scripts/preflight.py
    uv run scripts/preflight.py --target fly
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "syriac.db"
JSON_PATH = ROOT / "site" / "data.json"

# A deployment that only serves site/ has no backend, so secrets and admin
# accounts are irrelevant there.
STATIC_ONLY_TARGETS = {"pages"}


@dataclass
class Check:
    level: str  # OK | WARN | ERROR
    message: str
    hint: str = ""


def check_secret_key() -> Check:
    secret = os.environ.get("SECRET_KEY", "").strip()
    if not secret:
        return Check(
            "ERROR",
            "SECRET_KEY is not set",
            "Every restart invalidates all login tokens. "
            'Generate: python -c "import secrets; print(secrets.token_hex(32))"',
        )
    if len(secret) < 32:
        return Check("WARN", f"SECRET_KEY is short ({len(secret)} chars)", "Use at least 32 chars.")
    return Check("OK", "SECRET_KEY is set")


def check_allowed_origins() -> Check:
    origins = os.environ.get("ALLOWED_ORIGINS", "").strip()
    if not origins:
        return Check(
            "WARN",
            "ALLOWED_ORIGINS is unset (defaults to localhost)",
            "Fine when the site and API share an origin; set your domain otherwise.",
        )
    if "*" in origins:
        return Check(
            "ERROR",
            "ALLOWED_ORIGINS contains a wildcard",
            "With allow_credentials=True a wildcard origin exposes authenticated endpoints.",
        )
    return Check("OK", f"ALLOWED_ORIGINS restricted to {origins}")


def check_database() -> list[Check]:
    if not DB_PATH.exists():
        return [Check("ERROR", f"Database missing: {DB_PATH}", "Run scripts/fetch_openalex.py")]

    checks: list[Check] = []
    conn = sqlite3.connect(DB_PATH)
    try:
        live_works = conn.execute(
            "SELECT COUNT(*) FROM works WHERE status NOT IN ('deleted','excluded')"
        ).fetchone()[0]
        checks.append(
            Check("OK", f"database present with {live_works:,} live works")
            if live_works
            else Check("ERROR", "database has no live works")
        )

        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        # These are created by migrations, not by the ETL, so a fresh clone can
        # boot the API and then 500 on the first login.
        required = {"users", "user_claims", "pending_contributions", "notifications"}
        missing = sorted(required - tables)
        checks.append(
            Check(
                "ERROR",
                f"missing backend tables: {', '.join(missing)}",
                "Run scripts/migrate_phase3.py and scripts/migrate_notifications.py",
            )
            if missing
            else Check("OK", "backend tables present (users, claims, contributions, notifications)")
        )

        if "notifications" in tables:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(notifications)")}
            missing_cols = sorted({"kind", "dedupe_key", "link"} - columns)
            checks.append(
                Check(
                    "ERROR",
                    f"notifications table missing columns: {', '.join(missing_cols)}",
                    "Run scripts/migrate_notifications.py",
                )
                if missing_cols
                else Check("OK", "notifications schema is current")
            )

        if "users" in tables:
            admins = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0]
            checks.append(
                Check("OK", f"{admins} admin account(s)")
                if admins
                else Check(
                    "WARN",
                    "no admin account yet",
                    "The first account registered after deploy is bootstrapped as admin — "
                    "register it yourself immediately.",
                )
            )

        if "duplicate_candidates" in tables:
            pending = conn.execute(
                "SELECT COUNT(*) FROM duplicate_candidates WHERE review_status = 'pending'"
            ).fetchone()[0]
            if pending:
                checks.append(
                    Check(
                        "WARN",
                        f"{pending} duplicate candidate(s) awaiting review",
                        "Not blocking; curate via the admin UI after deploy.",
                    )
                )
    finally:
        conn.close()
    return checks


def check_export() -> list[Check]:
    if not JSON_PATH.exists():
        return [Check("ERROR", f"Export missing: {JSON_PATH}", "Run scripts/export_json.py")]

    checks = []
    size_mb = JSON_PATH.stat().st_size / (1024 * 1024)
    checks.append(Check("OK", f"site/data.json present ({size_mb:.1f} MB, gzip enabled in API)"))
    if size_mb > 12:
        checks.append(
            Check("WARN", f"export is large ({size_mb:.1f} MB)", "Slow first paint on mobile.")
        )

    if JSON_PATH.stat().st_mtime < DB_PATH.stat().st_mtime:
        checks.append(
            Check(
                "ERROR",
                "site/data.json is older than the database",
                "The deployed graph would not match the data. Run scripts/export_json.py",
            )
        )
    else:
        checks.append(Check("OK", "export is newer than the database"))

    try:
        with JSON_PATH.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        return checks + [Check("ERROR", f"export is not readable JSON: {exc}")]

    missing = sorted({"works", "authors", "clusters", "meta"} - set(data))
    checks.append(
        Check("ERROR", f"export missing keys: {', '.join(missing)}")
        if missing
        else Check("OK", f"export contains {len(data['works']):,} works")
    )
    return checks


def check_files(static_only: bool) -> list[Check]:
    checks = []
    if not static_only:
        for name in ("Dockerfile", "docker-compose.yml", "fly.toml"):
            path = ROOT / name
            checks.append(
                Check("OK", f"{name} present")
                if path.exists()
                else Check("WARN", f"{name} missing")
            )

    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8") if (ROOT / ".gitignore").exists() else ""
    checks.append(
        Check("OK", ".env is gitignored")
        if ".env" in gitignore
        else Check("ERROR", ".env is not gitignored", "Secrets could be committed.")
    )

    if (ROOT / ".env").exists():
        checks.append(Check("WARN", ".env exists locally", "Confirm it is not tracked by git."))
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--target",
        default="backend",
        choices=["backend", "fly", "docker", "pages"],
        help="Deployment target; 'pages' skips backend-only checks",
    )
    args = parser.parse_args()
    static_only = args.target in STATIC_ONLY_TARGETS

    checks: list[Check] = []
    if not static_only:
        checks.append(check_secret_key())
        checks.append(check_allowed_origins())
        checks.extend(check_database())
    checks.extend(check_export())
    checks.extend(check_files(static_only))

    print(f"Preflight for target: {args.target}")
    if static_only:
        print("(static target — secrets, database and admin checks skipped)")
    print()

    for check in checks:
        print(f"[{check.level:<5}] {check.message}")
        if check.hint and check.level != "OK":
            print(f"          → {check.hint}")

    errors = sum(1 for c in checks if c.level == "ERROR")
    warnings = sum(1 for c in checks if c.level == "WARN")
    print(f"\n{len(checks)} checks: {errors} error(s), {warnings} warning(s)")

    if errors:
        print("\nNOT ready to deploy — resolve the errors above.")
        raise SystemExit(1)
    print("\nReady to deploy.")


if __name__ == "__main__":
    main()
