"""One-off cleanup: permanently remove book reviews from data/syriac.db.

Book reviews are out of scope for this corpus (they're about a book, not
original scholarship, and their near-identical titles created false
collaboration/clustering signals — see PLAN.md). This deletes matching rows
from `works` and cascades to every table that references a work id.

Uses the same is_review_like() heuristic as compute_analysis.py (kept in
sync manually; both files intentionally define it standalone rather than
importing from one another, since compute_analysis.py is meant to run
standalone against a repo clone).

Usage:
    uv run scripts/remove_reviews.py
    uv run scripts/remove_reviews.py --dry-run   # preview only, no deletes

After running, re-run compute_analysis.py and export_json.py to refresh
the similarity graph, clusters, and site data with the cleaned corpus.
"""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "syriac.db"

REVIEW_TITLE_PREFIXES = ("book review", "review of", "review essay", "review article")
REVIEW_TITLE_SUBSTRINGS = ("book review",)
REVIEW_TITLE_MARKERS = ("isbn", "review:", " ed. ", "eds.)", "(hb)", "(pb)", " €", "$")
REVIEW_PAGECOUNT = re.compile(r"\d+\s*pp\.")
REVIEW_BY_AUTHOR_SUFFIX = re.compile(r"\.\s*by\s+[a-z][a-z.\s]{2,40}\.?\s*$", re.IGNORECASE)


def is_review_like(title: str, work_type: str) -> bool:
    if work_type in ("review", "book-review"):
        return True
    t = (title or "").strip().lower()
    if any(t.startswith(p) for p in REVIEW_TITLE_PREFIXES):
        return True
    if any(s in t for s in REVIEW_TITLE_SUBSTRINGS):
        return True
    if any(marker in t for marker in REVIEW_TITLE_MARKERS):
        return True
    if REVIEW_PAGECOUNT.search(t):
        return True
    return bool(REVIEW_BY_AUTHOR_SUFFIX.search(t))


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT id, title, work_type FROM works").fetchall()

    review_ids = [wid for wid, title, wtype in rows if is_review_like(title, wtype)]
    print(f"Found {len(review_ids)} review-like works out of {len(rows)} total.")

    if dry_run:
        print("\n--dry-run: showing first 20 titles that would be removed:")
        sample = [t for wid, t, wtype in rows if wid in set(review_ids)][:20]
        for t in sample:
            print(f"  - {t}")
        print("\nNo changes made (dry run).")
        conn.close()
        return

    if not review_ids:
        print("Nothing to remove.")
        conn.close()
        return

    placeholders = ",".join("?" * len(review_ids))
    conn.execute(f"DELETE FROM authorship WHERE work_id IN ({placeholders})", review_ids)
    conn.execute(
        f"DELETE FROM citations WHERE citing_work_id IN ({placeholders}) OR cited_work_id IN ({placeholders})",
        review_ids + review_ids,
    )
    conn.execute(
        f"DELETE FROM work_references WHERE work_id IN ({placeholders}) OR referenced_work_id IN ({placeholders})",
        review_ids + review_ids,
    )
    conn.execute(f"DELETE FROM works WHERE id IN ({placeholders})", review_ids)

    # Phase 1 analysis tables (similarity_edges, work_clusters, clusters,
    # collaboration_candidates) are fully dropped and rebuilt by
    # compute_analysis.py on every run, so no cleanup needed here for those.

    # Authors left with zero works after removal are orphaned; drop them too.
    orphan_authors = [
        row[0]
        for row in conn.execute(
            "SELECT id FROM authors WHERE id NOT IN (SELECT DISTINCT author_id FROM authorship)"
        )
    ]
    if orphan_authors:
        placeholders_a = ",".join("?" * len(orphan_authors))
        conn.execute(f"DELETE FROM authors WHERE id IN ({placeholders_a})", orphan_authors)

    conn.commit()

    n_works = conn.execute("SELECT COUNT(*) FROM works").fetchone()[0]
    n_authors = conn.execute("SELECT COUNT(*) FROM authors").fetchone()[0]
    print(f"Removed {len(review_ids)} works and {len(orphan_authors)} now-orphaned authors.")
    print(f"Remaining: works={n_works} authors={n_authors}")
    print("\nNext: re-run `uv run scripts/compute_analysis.py` then `uv run scripts/export_json.py`.")

    conn.close()


if __name__ == "__main__":
    main()
