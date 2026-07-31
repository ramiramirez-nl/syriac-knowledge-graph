"""Check which reviews are caught by which rule."""
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "syriac.db"

REVIEW_TITLE_PREFIXES = ("book review", "review of", "review essay", "review article")
REVIEW_TITLE_SUBSTRINGS = ("book review",)
REVIEW_TITLE_MARKERS = ("isbn", "review:", " ed. ", "eds.)", "(hb)", "(pb)", " €", "$")
REVIEW_PAGECOUNT = re.compile(r"\d+\s*pp\.")
REVIEW_BY_AUTHOR_SUFFIX = re.compile(r"\.\s*by\s+[a-z][a-z.\s]{2,40}\.?\s*$", re.IGNORECASE)

conn = sqlite3.connect(DB_PATH)
rows = conn.execute("SELECT id, title, work_type FROM works").fetchall()

by_rule = {
    "work_type": [],
    "prefix": [],
    "substring": [],
    "marker": [],
    "pagecount": [],
    "by_author_suffix": [],
}

for wid, title, wtype in rows:
    t = (title or "").strip().lower()
    if wtype in ("review", "book-review"):
        by_rule["work_type"].append((wid, title, wtype))
    elif any(t.startswith(p) for p in REVIEW_TITLE_PREFIXES):
        by_rule["prefix"].append((wid, title, wtype))
    elif any(s in t for s in REVIEW_TITLE_SUBSTRINGS):
        by_rule["substring"].append((wid, title, wtype))
    elif any(marker in t for marker in REVIEW_TITLE_MARKERS):
        by_rule["marker"].append((wid, title, wtype))
    elif REVIEW_PAGECOUNT.search(t):
        by_rule["pagecount"].append((wid, title, wtype))
    elif REVIEW_BY_AUTHOR_SUFFIX.search(t):
        by_rule["by_author_suffix"].append((wid, title, wtype))

for rule, items in by_rule.items():
    print(f"\n=== {rule}: {len(items)} matches ===")
    for wid, title, wtype in items[:5]:
        print(f"  [{wtype}] {title[:100]}")
    if len(items) > 5:
        print(f"  ... and {len(items)-5} more")
