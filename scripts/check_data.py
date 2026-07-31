"""Validate database integrity and the generated static-site export.

Usage:
    uv run scripts/check_data.py
    uv run scripts/check_data.py --json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "syriac.db"
JSON_PATH = ROOT / "site" / "data.json"
REQUIRED_TABLES = {
    "works", "authors", "authorship", "citations", "work_references",
    "similarity_edges", "work_clusters", "clusters", "collaboration_candidates",
}


@dataclass
class Result:
    level: str
    message: str


def scalar(conn: sqlite3.Connection, sql: str) -> int:
    return int(conn.execute(sql).fetchone()[0])


def check_database(conn: sqlite3.Connection) -> list[Result]:
    results: list[Result] = []
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    missing = sorted(REQUIRED_TABLES - tables)
    if missing:
        return [Result("ERROR", f"Missing tables: {', '.join(missing)}")]

    checks = [
        ("authorship rows with a missing work", "SELECT COUNT(*) FROM authorship a LEFT JOIN works w ON w.id=a.work_id WHERE w.id IS NULL"),
        ("authorship rows with a missing author", "SELECT COUNT(*) FROM authorship a LEFT JOIN authors x ON x.id=a.author_id WHERE x.id IS NULL"),
        ("citation rows with a missing source work", "SELECT COUNT(*) FROM citations c LEFT JOIN works w ON w.id=c.citing_work_id WHERE w.id IS NULL"),
        ("citation rows with a missing target work", "SELECT COUNT(*) FROM citations c LEFT JOIN works w ON w.id=c.cited_work_id WHERE w.id IS NULL"),
        ("self-citations", "SELECT COUNT(*) FROM citations WHERE citing_work_id=cited_work_id"),
        ("similarity rows with a missing first work", "SELECT COUNT(*) FROM similarity_edges e LEFT JOIN works w ON w.id=e.work_id_a WHERE w.id IS NULL"),
        ("similarity rows with a missing second work", "SELECT COUNT(*) FROM similarity_edges e LEFT JOIN works w ON w.id=e.work_id_b WHERE w.id IS NULL"),
        ("cluster assignments with a missing work", "SELECT COUNT(*) FROM work_clusters c LEFT JOIN works w ON w.id=c.work_id WHERE w.id IS NULL"),
        ("collaboration rows with a missing first author", "SELECT COUNT(*) FROM collaboration_candidates c LEFT JOIN authors a ON a.id=c.author_id_a WHERE a.id IS NULL"),
        ("collaboration rows with a missing second author", "SELECT COUNT(*) FROM collaboration_candidates c LEFT JOIN authors a ON a.id=c.author_id_b WHERE a.id IS NULL"),
        ("works without a title", "SELECT COUNT(*) FROM works WHERE title IS NULL OR trim(title)=''"),
        ("authors without a name", "SELECT COUNT(*) FROM authors WHERE name IS NULL OR trim(name)=''"),
        ("orphan authors", "SELECT COUNT(*) FROM authors a LEFT JOIN authorship x ON x.author_id=a.id WHERE x.author_id IS NULL"),
    ]
    for label, sql in checks:
        count = scalar(conn, sql)
        results.append(Result("OK" if count == 0 else "ERROR", f"{label}: {count}"))

    works = scalar(conn, "SELECT COUNT(*) FROM works")
    assignments = scalar(conn, "SELECT COUNT(*) FROM work_clusters")
    results.append(Result("OK" if works == assignments else "ERROR", f"cluster coverage: {assignments}/{works}"))

    invalid_years = scalar(conn, "SELECT COUNT(*) FROM works WHERE year IS NOT NULL AND (year < 1500 OR year > CAST(strftime('%Y','now') AS INTEGER)+1)")
    results.append(Result("OK" if invalid_years == 0 else "WARN", f"implausible publication years: {invalid_years}"))

    duplicate_dois = scalar(conn, "SELECT COUNT(*) FROM (SELECT lower(trim(doi)) FROM works WHERE doi IS NOT NULL AND trim(doi)<>'' GROUP BY lower(trim(doi)) HAVING COUNT(*)>1)")
    results.append(Result("WARN" if duplicate_dois else "OK", f"duplicate DOI groups: {duplicate_dois}"))

    bad_cluster_sizes = scalar(conn, "SELECT COUNT(*) FROM clusters c WHERE c.size <> (SELECT COUNT(*) FROM work_clusters w WHERE w.cluster_id=c.cluster_id)")
    results.append(Result("OK" if bad_cluster_sizes == 0 else "ERROR", f"incorrect cluster sizes: {bad_cluster_sizes}"))
    return results


def check_export(conn: sqlite3.Connection) -> list[Result]:
    if not JSON_PATH.exists():
        return [Result("ERROR", f"Missing export: {JSON_PATH}")]
    try:
        with JSON_PATH.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        return [Result("ERROR", f"Cannot read export: {exc}")]

    # The export excludes soft-deleted/excluded works and any edges touching
    # them (see export_json.py), so the expected counts must mirror that.
    active = "status NOT IN ('deleted','excluded')"
    expected = {
        "workCount": scalar(conn, f"SELECT COUNT(*) FROM works WHERE {active}"),
        "authorCount": scalar(conn, "SELECT COUNT(*) FROM authors WHERE id IN (SELECT DISTINCT author_id FROM authorship)"),
        "citationCount": scalar(conn, f"""SELECT COUNT(*) FROM citations c
            JOIN works a ON a.id=c.citing_work_id AND a.{active}
            JOIN works b ON b.id=c.cited_work_id AND b.{active}"""),
        "similarityEdgeCount": scalar(conn, f"""SELECT COUNT(*) FROM similarity_edges e
            JOIN works a ON a.id=e.work_id_a AND a.{active}
            JOIN works b ON b.id=e.work_id_b AND b.{active}"""),
        "clusterCount": scalar(conn, "SELECT COUNT(*) FROM clusters WHERE size >= 3"),
        "collaborationCandidateCount": scalar(conn, "SELECT COUNT(*) FROM collaboration_candidates"),
    }
    meta = data.get("meta", {})
    results = []
    for key, value in expected.items():
        actual = meta.get(key)
        results.append(Result("OK" if actual == value else "ERROR", f"export {key}: {actual} (database: {value})"))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Syriac Studies data integrity.")
    parser.add_argument("--json", action="store_true", help="Print a machine-readable report")
    args = parser.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")

    with sqlite3.connect(DB_PATH) as conn:
        results = check_database(conn) + check_export(conn)

    errors = sum(r.level == "ERROR" for r in results)
    warnings = sum(r.level == "WARN" for r in results)
    if args.json:
        print(json.dumps({"errors": errors, "warnings": warnings, "checks": [r.__dict__ for r in results]}, indent=2))
    else:
        for result in results:
            print(f"[{result.level:5}] {result.message}")
        print(f"\n{len(results)} checks: {errors} error(s), {warnings} warning(s)")
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
