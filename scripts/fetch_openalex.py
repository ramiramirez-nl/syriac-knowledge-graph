"""Fetch Syriac Studies works, authors, and citation edges from OpenAlex into SQLite.

Usage:
    uv run scripts/fetch_openalex.py

Reads search terms from config/terms.yaml, paginates the OpenAlex /works endpoint
with title.search filters, deduplicates across terms, and writes a normalized
SQLite database at data/syriac.db. Citation edges are kept only between two
works that are both in the fetched set (internal citation network) so the
graph reflects in-corpus relationships rather than dangling references.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from urllib.parse import quote

import requests
import yaml
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "terms.yaml"
DB_PATH = ROOT / "data" / "syriac.db"

SELECT_FIELDS = ",".join(
    [
        "id",
        "doi",
        "display_name",
        "publication_year",
        "cited_by_count",
        "type",
        "primary_location",
        "authorships",
        "referenced_works",
    ]
)


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def short_id(openalex_url: str) -> str:
    """Turn 'https://openalex.org/W123' into 'W123'."""
    return openalex_url.rsplit("/", 1)[-1]


def is_excluded(work: dict, exclude_terms: list[str]) -> bool:
    """Return True when a configured exclusion occurs in the work title."""
    title = (work.get("display_name") or "").casefold()
    return any(term.casefold() in title for term in exclude_terms)


def build_session() -> requests.Session:
    """Create an API session resilient to transient rate limits and failures."""
    retry = Retry(
        total=5,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def fetch_term(session: requests.Session, base_url: str, mailto: str, per_page: int, term: str, from_date: str = None) -> list[dict]:
    """Page through all works whose title matches `term`."""
    results: list[dict] = []
    cursor = "*"
    filter_value = quote(f'title.search:"{term}"' if " " in term else f"title.search:{term}")
    if from_date:
        filter_value += f",from_updated_date:{from_date}"
    while cursor:
        url = (
            f"{base_url}/works?filter={filter_value}"
            f"&per-page={per_page}&cursor={cursor}&select={SELECT_FIELDS}&mailto={mailto}"
        )
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        results.extend(payload["results"])
        cursor = payload["meta"].get("next_cursor")
        if not payload["results"]:
            break
        time.sleep(0.05)
    return results


def build_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS works (
            id TEXT PRIMARY KEY,
            doi TEXT,
            title TEXT,
            year INTEGER,
            venue TEXT,
            work_type TEXT,
            cited_by_count INTEGER,
            source TEXT DEFAULT 'openalex',
            status TEXT DEFAULT 'auto'
        );

        CREATE TABLE IF NOT EXISTS authors (
            id TEXT PRIMARY KEY,
            name TEXT,
            source TEXT DEFAULT 'openalex',
            status TEXT DEFAULT 'auto'
        );

        CREATE TABLE IF NOT EXISTS authorship (
            work_id TEXT REFERENCES works(id),
            author_id TEXT REFERENCES authors(id),
            author_position TEXT,
            PRIMARY KEY (work_id, author_id)
        );

        CREATE TABLE IF NOT EXISTS citations (
            citing_work_id TEXT REFERENCES works(id),
            cited_work_id TEXT REFERENCES works(id),
            PRIMARY KEY (citing_work_id, cited_work_id)
        );

        -- Full reference lists per work, including references to works OUTSIDE
        -- the corpus (e.g. books not indexed by OpenAlex as standalone works).
        -- Used for bibliographic coupling: two corpus works sharing an external
        -- reference is a meaningful relatedness signal even with no internal edge.
        CREATE TABLE IF NOT EXISTS work_references (
            work_id TEXT REFERENCES works(id),
            referenced_work_id TEXT,
            PRIMARY KEY (work_id, referenced_work_id)
        );

        CREATE INDEX IF NOT EXISTS idx_authorship_author ON authorship(author_id);
        CREATE INDEX IF NOT EXISTS idx_citations_cited ON citations(cited_work_id);
        CREATE INDEX IF NOT EXISTS idx_workrefs_ref ON work_references(referenced_work_id);

        CREATE TABLE IF NOT EXISTS sync_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            hashed_password TEXT,
            role TEXT DEFAULT 'user'
        );

        CREATE TABLE IF NOT EXISTS user_claims (
            user_id INTEGER REFERENCES users(id),
            author_id TEXT REFERENCES authors(id),
            status TEXT DEFAULT 'pending',
            PRIMARY KEY(user_id, author_id)
        );
        """
    )


def upsert_work(conn: sqlite3.Connection, work: dict) -> None:
    work_id = short_id(work["id"])
    venue = None
    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    venue = source.get("display_name")

    conn.execute(
        """
        INSERT INTO works (id, doi, title, year, venue, work_type, cited_by_count, source, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'openalex', 'auto')
        ON CONFLICT(id) DO UPDATE SET
            doi=excluded.doi, title=excluded.title, year=excluded.year,
            venue=excluded.venue, work_type=excluded.work_type,
            cited_by_count=excluded.cited_by_count
        """,
        (
            work_id,
            work.get("doi"),
            work.get("display_name"),
            work.get("publication_year"),
            venue,
            work.get("type"),
            work.get("cited_by_count", 0),
        ),
    )

    # The API is authoritative for OpenAlex authorship. Clear old links first
    # so removed/corrected authors do not survive an incremental refresh.
    conn.execute("DELETE FROM authorship WHERE work_id = ?", (work_id,))

    for authorship in work.get("authorships", []):
        author = authorship.get("author") or {}
        author_id = author.get("id")
        if not author_id:
            continue
        author_id = short_id(author_id)
        conn.execute(
            """
            INSERT INTO authors (id, name, source, status)
            VALUES (?, ?, 'openalex', 'auto')
            ON CONFLICT(id) DO UPDATE SET name=excluded.name
            """,
            (author_id, author.get("display_name")),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO authorship (work_id, author_id, author_position)
            VALUES (?, ?, ?)
            """,
            (work_id, author_id, authorship.get("author_position")),
        )


def link_citations(conn: sqlite3.Connection, works: list[dict]) -> None:
    """Refresh full references and internal-only citations for fetched works."""
    known_ids = {row[0] for row in conn.execute("SELECT id FROM works")}
    fetched_ids = [short_id(work["id"]) for work in works]
    conn.executemany("DELETE FROM work_references WHERE work_id = ?", ((wid,) for wid in fetched_ids))
    conn.executemany("DELETE FROM citations WHERE citing_work_id = ?", ((wid,) for wid in fetched_ids))

    for work in works:
        citing_id = short_id(work["id"])
        for ref in work.get("referenced_works", []):
            cited_id = short_id(ref)
            if cited_id == citing_id:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO work_references (work_id, referenced_work_id) VALUES (?, ?)",
                (citing_id, cited_id),
            )
            if cited_id in known_ids:
                conn.execute(
                    "INSERT OR IGNORE INTO citations (citing_work_id, cited_work_id) VALUES (?, ?)",
                    (citing_id, cited_id),
                )


def main() -> None:
    cfg = load_config()
    api_cfg = cfg["api"]
    terms = cfg["include_terms"]
    exclude_terms = cfg.get("exclude_terms") or []

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    build_schema(conn)

    last_updated_row = conn.execute("SELECT value FROM sync_meta WHERE key = 'last_updated'").fetchone()
    from_date = last_updated_row[0] if last_updated_row else None
    if from_date:
        print(f"Incremental update: fetching works updated since {from_date}")
    
    today_str = time.strftime("%Y-%m-%d")

    session = build_session()
    seen_ids: set[str] = set()
    all_works: list[dict] = []

    for term in terms:
        print(f"Fetching term: {term!r} ...")
        works = fetch_term(session, api_cfg["base_url"], api_cfg["mailto"], api_cfg["per_page"], term, from_date)
        new_count = 0
        excluded_count = 0
        for w in works:
            wid = short_id(w["id"])
            if wid in seen_ids:
                continue
            if is_excluded(w, exclude_terms):
                excluded_count += 1
                continue
            seen_ids.add(wid)
            all_works.append(w)
            upsert_work(conn, w)
            new_count += 1
        conn.commit()
        print(
            f"  -> {len(works)} results, {new_count} new, {excluded_count} excluded "
            f"(total so far: {len(seen_ids)})"
        )

    print("Linking internal citation edges...")
    link_citations(conn, all_works)
    conn.execute("DELETE FROM authors WHERE id NOT IN (SELECT DISTINCT author_id FROM authorship)")
    
    conn.execute("INSERT OR REPLACE INTO sync_meta (key, value) VALUES ('last_updated', ?)", (today_str,))
    conn.commit()

    n_works = conn.execute("SELECT COUNT(*) FROM works").fetchone()[0]
    n_authors = conn.execute("SELECT COUNT(*) FROM authors").fetchone()[0]
    n_citations = conn.execute("SELECT COUNT(*) FROM citations").fetchone()[0]
    n_authorship = conn.execute("SELECT COUNT(*) FROM authorship").fetchone()[0]
    n_references = conn.execute("SELECT COUNT(*) FROM work_references").fetchone()[0]
    print(
        f"\nDone. works={n_works} authors={n_authors} authorship_links={n_authorship} "
        f"internal_citations={n_citations} total_references={n_references}"
    )
    print(f"Database written to {DB_PATH}")

    conn.close()


if __name__ == "__main__":
    main()
