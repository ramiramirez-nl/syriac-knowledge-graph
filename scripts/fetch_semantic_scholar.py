"""Enrich citation data using Semantic Scholar API.

Looks up works by DOI or title in Semantic Scholar, fetches their
citation/reference lists, and adds new citation edges to the SQLite
database for works that are already in our corpus.

Semantic Scholar API: https://api.semanticscholar.org/
Rate limit: 100 requests per 5 minutes (no API key) = ~1 req/3s

Usage:
    uv run scripts/fetch_semantic_scholar.py
    uv run scripts/fetch_semantic_scholar.py --limit 500   # limit number of works to look up
"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "syriac.db"

S2_API = "https://api.semanticscholar.org/graph/v1"


def create_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=5, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def get_limit() -> int:
    for i, arg in enumerate(sys.argv):
        if arg == "--limit" and i + 1 < len(sys.argv):
            return int(sys.argv[i + 1])
    return 0  # 0 = no limit


def lookup_by_doi(session: requests.Session, doi: str) -> dict | None:
    """Look up a paper by DOI in Semantic Scholar."""
    url = f"{S2_API}/paper/DOI:{doi}?fields=externalIds,citations.externalIds,references.externalIds"
    try:
        resp = session.get(url, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 404:
            return None
        elif resp.status_code == 429:
            # Rate limited, wait and retry
            time.sleep(10)
            resp = session.get(url, timeout=30)
            if resp.status_code == 200:
                return resp.json()
        return None
    except Exception:
        return None


def lookup_by_title(session: requests.Session, title: str) -> dict | None:
    """Look up a paper by title search in Semantic Scholar."""
    # Clean title of HTML tags
    import re
    clean_title = re.sub(r'<[^>]+>', '', title).strip()
    if len(clean_title) < 10:
        return None
    
    url = f"{S2_API}/paper/search?query={quote(clean_title[:200])}&limit=1&fields=externalIds,citations.externalIds,references.externalIds"
    try:
        resp = session.get(url, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("data") and len(data["data"]) > 0:
                # Verify title similarity
                result = data["data"][0]
                result_title = result.get("title", "").lower()
                if clean_title.lower()[:50] in result_title or result_title[:50] in clean_title.lower():
                    return result
        elif resp.status_code == 429:
            time.sleep(10)
            return None
        return None
    except Exception:
        return None


def openalex_id_from_s2(external_ids: dict | None) -> str | None:
    """Extract an OpenAlex-compatible ID from Semantic Scholar external IDs."""
    if not external_ids:
        return None
    # S2 sometimes has OpenAlex IDs directly
    oa_id = external_ids.get("OpenAlex")
    if oa_id:
        # Convert full URL to short ID
        if "/" in oa_id:
            return oa_id.split("/")[-1]
        return oa_id
    return None


def main() -> None:
    limit = get_limit()
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # Get all work IDs in our corpus for fast lookup
    corpus_ids = set()
    doi_to_id = {}
    id_to_doi = {}
    
    for row in conn.execute("SELECT id, title FROM works"):
        corpus_ids.add(row["id"])
    
    # Check if works table has a doi column
    cols = [r[1] for r in conn.execute("PRAGMA table_info(works)")]
    has_doi = "doi" in cols
    
    if has_doi:
        for row in conn.execute("SELECT id, doi FROM works WHERE doi IS NOT NULL AND doi != ''"):
            doi_to_id[row["doi"]] = row["id"]
            id_to_doi[row["id"]] = row["doi"]
    
    # Get existing citations to avoid duplicates
    existing_citations = set()
    for row in conn.execute("SELECT citing_work_id, cited_work_id FROM citations"):
        existing_citations.add((row["citing_work_id"], row["cited_work_id"]))
    
    print(f"Corpus: {len(corpus_ids)} works, {len(existing_citations)} existing citations")
    print(f"Works with DOI: {len(doi_to_id)}")
    
    # Strategy: Look up works that have DOIs first (much more reliable)
    # Then try title search for the rest
    session = create_session()
    
    works_to_check = []
    if has_doi:
        for row in conn.execute("SELECT id, doi, title FROM works WHERE doi IS NOT NULL AND doi != '' ORDER BY cited_by_count DESC"):
            works_to_check.append({"id": row["id"], "doi": row["doi"], "title": row["title"]})
    
    # Also add works without DOI, using title search
    for row in conn.execute("SELECT id, title FROM works WHERE id NOT IN (SELECT id FROM works WHERE doi IS NOT NULL AND doi != '') ORDER BY cited_by_count DESC"):
        works_to_check.append({"id": row["id"], "doi": None, "title": row["title"]})
    
    if limit > 0:
        works_to_check = works_to_check[:limit]
    
    print(f"Will check {len(works_to_check)} works against Semantic Scholar\n")
    
    new_citations = 0
    checked = 0
    found = 0
    errors = 0
    
    for i, work in enumerate(works_to_check):
        if i > 0 and i % 50 == 0:
            print(f"  Progress: {i}/{len(works_to_check)} checked, {found} found in S2, {new_citations} new citations added")
        
        # Rate limiting: ~1 request per 3 seconds for no-API-key tier
        time.sleep(3.2)
        
        result = None
        if work["doi"]:
            result = lookup_by_doi(session, work["doi"])
        
        if result is None and work["title"]:
            time.sleep(1)  # Extra delay for title searches
            result = lookup_by_title(session, work["title"])
        
        if result is None:
            continue
        
        found += 1
        checked += 1
        
        # Process citations (papers this work cites)
        references = result.get("references") or []
        for ref in references:
            ref_ext = ref.get("externalIds") or {}
            ref_oa_id = openalex_id_from_s2(ref_ext)
            if ref_oa_id and ref_oa_id in corpus_ids:
                pair = (work["id"], ref_oa_id)
                if pair not in existing_citations:
                    try:
                        conn.execute(
                            "INSERT INTO citations (citing_work_id, cited_work_id) VALUES (?, ?)",
                            pair
                        )
                        existing_citations.add(pair)
                        new_citations += 1
                    except sqlite3.IntegrityError:
                        pass
        
        # Process citations (papers citing this work)
        citations = result.get("citations") or []
        for cit in citations:
            cit_ext = cit.get("externalIds") or {}
            cit_oa_id = openalex_id_from_s2(cit_ext)
            if cit_oa_id and cit_oa_id in corpus_ids:
                pair = (cit_oa_id, work["id"])
                if pair not in existing_citations:
                    try:
                        conn.execute(
                            "INSERT INTO citations (citing_work_id, cited_work_id) VALUES (?, ?)",
                            pair
                        )
                        existing_citations.add(pair)
                        new_citations += 1
                    except sqlite3.IntegrityError:
                        pass
        
        # Commit every 100 works
        if found % 100 == 0:
            conn.commit()
    
    conn.commit()
    
    total_citations = conn.execute("SELECT COUNT(*) FROM citations").fetchone()[0]
    
    print(f"\n=== Complete ===")
    print(f"Works checked: {len(works_to_check)}")
    print(f"Found in Semantic Scholar: {found}")
    print(f"New citation edges added: {new_citations}")
    print(f"Total citations now: {total_citations} (was {len(existing_citations) - new_citations})")
    print(f"\nNext: re-run `uv run scripts/compute_analysis.py` then `uv run scripts/export_json.py`.")
    
    conn.close()


if __name__ == "__main__":
    main()
