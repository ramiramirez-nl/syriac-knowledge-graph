"""Resolve same-DOI duplicate works: merge the safe ones, flag the rest.

A shared DOI is the strongest duplicate signal in the corpus, but it is not
proof: publishers reuse a DOI across editions ("The Bible in the Syriac
Tradition" 2002 vs "...(Third Edition)" 2021), and those are genuinely
different works that must stay separate.

So this script splits every same-DOI group in two:

  auto  — the records differ only cosmetically (one title is a prefix/subtitle
          variant of the other, no edition marker, years compatible). These are
          merged into the record with the most citations, which keeps the
          better-connected node.
  manual— anything with an edition marker or an unexplained year gap. These are
          written to `duplicate_candidates` with review_status='pending' so a
          curator decides in the admin UI. Nothing is deleted.

Merging reuses the same relation remapping as the API's /api/works/merge:
citations, references, authorship, similarity edges, clusters and manuscript
details are moved to the surviving id, then the loser is soft-deleted
(status='deleted'), never dropped — Phase 2 curation is reversible by design.

Usage:
    uv run scripts/resolve_duplicates.py --dry-run
    uv run scripts/resolve_duplicates.py
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Titles in this corpus contain non-Latin-1 characters (and OpenAlex mojibake);
# the default Windows console codepage cannot encode them and would crash the
# run on a print(). Match the approach already used in remove_reviews.py.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
DB_PATH = ROOT / "data" / "syriac.db"

from find_duplicates import ensure_schema, normalize_text  # noqa: E402

# Titles containing these are treated as distinct editions/volumes, never merged
# automatically regardless of how similar the rest of the record looks.
EDITION_MARKERS = re.compile(
    r"\b("
    r"(second|third|fourth|fifth|revised|new|expanded|enlarged|abridged)\s+edition"
    r"|\d+(st|nd|rd|th)\s+edition"
    r"|edition\s+\d+"
    r"|part\s+(one|two|three|[ivx\d]+)\b"
    r"|vol(ume)?\.?\s*[ivx\d]+\b"
    r"|tome\s+[ivx\d]+\b"
    r")",
    re.IGNORECASE,
)

# Two records published this far apart are suspicious even with an identical
# title: usually a reprint/reissue rather than an indexing duplicate.
MAX_SAFE_YEAR_GAP = 3


def titles_are_variants(a: str, b: str) -> bool:
    """True when one normalized title is the other plus a subtitle.

    "The Syriac Dot" vs "The Syriac Dot: A Short History" -> True
    "Syriac Grammar" vs "Elements of Syriac Grammar"       -> False (prefix
    differs, so these are different works despite the shared tail).
    """
    na, nb = normalize_text(a), normalize_text(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    # Require a word boundary so "syriac dot" does not match "syriac dotted".
    return longer.startswith(shorter + " ")


def classify(group: list[sqlite3.Row]) -> tuple[str, str]:
    """Decide what to do with one same-DOI group.

    Returns (decision, reason) where decision is 'auto' or 'manual'.
    """
    if len(group) != 2:
        return "manual", f"group of {len(group)} records needs a curator"

    a, b = group
    titles = [(a["title"] or ""), (b["title"] or "")]

    for title in titles:
        marker = EDITION_MARKERS.search(title)
        if marker:
            return "manual", f"edition/volume marker: '{marker.group(0).strip()}'"

    if not titles_are_variants(*titles):
        return "manual", "titles are not prefix/subtitle variants"

    years = [a["year"], b["year"]]
    if all(y is not None for y in years):
        gap = abs(years[0] - years[1])
        if gap > MAX_SAFE_YEAR_GAP:
            return "manual", f"publication years differ by {gap}"

    return "auto", "same DOI, subtitle-only title difference, compatible years"


def has_mojibake(text: str | None) -> bool:
    """U+FFFD marks bytes OpenAlex could not decode (e.g. 'Erica\ufffdC.\ufffdD.')."""
    return "\ufffd" in (text or "")


def pick_survivor(group: list[sqlite3.Row]) -> tuple[sqlite3.Row, sqlite3.Row]:
    """Keep the best-connected, most descriptive record.

    Ranking, highest first:
      1. clean title  — never let a mojibake record win, otherwise the merge
         permanently enshrines the corrupted spelling on the surviving node.
      2. citation count — the node other works actually point at.
      3. longer title — keeps the subtitle.
      4. id — stable tiebreak so runs are reproducible.
    """
    ranked = sorted(
        group,
        key=lambda r: (
            not has_mojibake(r["title"]),
            r["cited_by_count"] or 0,
            len(r["title"] or ""),
            r["id"],
        ),
        reverse=True,
    )
    return ranked[0], ranked[1]


def merge_work(conn: sqlite3.Connection, keep_id: str, drop_id: str) -> None:
    """Move every relation from drop_id to keep_id, then soft-delete drop_id.

    Mirrors api/routes/works.py::merge_works. UPDATE OR IGNORE lets an edge that
    would collide with an existing one fail silently; the follow-up DELETE then
    removes the leftover row.
    """
    remaps = [
        ("citations", "citing_work_id"),
        ("citations", "cited_work_id"),
        ("authorship", "work_id"),
        ("work_references", "work_id"),
        ("work_references", "referenced_work_id"),
        ("similarity_edges", "work_id_a"),
        ("similarity_edges", "work_id_b"),
        ("work_clusters", "work_id"),
        ("manuscript_details", "work_id"),
    ]
    for table, column in remaps:
        conn.execute(
            f"UPDATE OR IGNORE {table} SET {column} = ? WHERE {column} = ?", (keep_id, drop_id)
        )
        conn.execute(f"DELETE FROM {table} WHERE {column} = ?", (drop_id,))

    # Remapping can create self-links; those are exactly what check_data.py
    # reports as errors, so clear them here rather than leaving them behind.
    conn.execute("DELETE FROM citations WHERE citing_work_id = cited_work_id")
    conn.execute("DELETE FROM work_references WHERE work_id = referenced_work_id")
    conn.execute("DELETE FROM similarity_edges WHERE work_id_a = work_id_b")

    # The surviving record inherits the merged citation count so the node keeps
    # its true weight in the graph.
    conn.execute(
        """UPDATE works SET cited_by_count = (
               SELECT COALESCE(MAX(cited_by_count), 0) FROM works WHERE id IN (?, ?)
           ) WHERE id = ?""",
        (keep_id, drop_id, keep_id),
    )

    # The survivor is chosen by citation count, which can leave the shorter,
    # less informative title on the node ("Bethlehem's Syriac Christians" while
    # the loser carried the full subtitle). Since auto-merge only runs on
    # prefix/subtitle variants, adopting the longer title is safe — unless it
    # carries mojibake, in which case the clean one wins.
    keep_title, drop_title, keep_venue, drop_venue = conn.execute(
        """SELECT k.title, d.title, k.venue, d.venue
           FROM works k, works d WHERE k.id = ? AND d.id = ?""",
        (keep_id, drop_id),
    ).fetchone()

    if (
        drop_title
        and len(drop_title) > len(keep_title or "")
        and not has_mojibake(drop_title)
        and not has_mojibake(keep_title)
    ):
        conn.execute("UPDATE works SET title = ? WHERE id = ?", (drop_title, keep_id))

    # Same for a missing venue: prefer real metadata over NULL.
    if not keep_venue and drop_venue:
        conn.execute("UPDATE works SET venue = ? WHERE id = ?", (drop_venue, keep_id))

    conn.execute("UPDATE works SET status = 'deleted' WHERE id = ?", (drop_id,))


def queue_for_review(conn: sqlite3.Connection, a: sqlite3.Row, b: sqlite3.Row, reason: str) -> None:
    """Add a same-DOI pair to the curator queue without touching the works."""
    first, second = sorted([a["id"], b["id"]])
    years = [a["year"], b["year"]]
    year_difference = abs(years[0] - years[1]) if all(y is not None for y in years) else None
    conn.execute(
        """
        INSERT INTO duplicate_candidates
            (work_id_a, work_id_b, score, title_similarity, same_doi,
             year_difference, venue_similarity, reasons, review_status, detected_at)
        VALUES (?, ?, 1.0, 1.0, 1, ?, 0, ?, 'pending', ?)
        ON CONFLICT(work_id_a, work_id_b) DO UPDATE SET
            same_doi = 1,
            reasons = excluded.reasons
        WHERE duplicate_candidates.review_status = 'pending'
        """,
        (first, second, year_difference, f"same DOI; {reason}", datetime.now(timezone.utc).isoformat()),
    )


def same_doi_groups(conn: sqlite3.Connection) -> list[list[sqlite3.Row]]:
    dois = conn.execute(
        """
        SELECT doi FROM works
        WHERE doi IS NOT NULL AND TRIM(doi) != ''
          AND status NOT IN ('deleted', 'excluded')
        GROUP BY doi HAVING COUNT(*) > 1
        """
    ).fetchall()

    groups = []
    for row in dois:
        members = conn.execute(
            """SELECT id, title, year, venue, cited_by_count FROM works
               WHERE doi = ? AND status NOT IN ('deleted', 'excluded')
               ORDER BY id""",
            (row["doi"],),
        ).fetchall()
        groups.append(members)
    return groups


def resolve(conn: sqlite3.Connection, dry_run: bool = False) -> dict:
    ensure_schema(conn)
    groups = same_doi_groups(conn)
    merged = queued = 0

    for group in groups:
        decision, reason = classify(group)
        if decision == "auto":
            keep, drop = pick_survivor(group)
            print(f"[MERGE ] {drop['id']} -> {keep['id']}  ({reason})")
            print(f"         keep: {(keep['title'] or '')[:70]}")
            print(f"         drop: {(drop['title'] or '')[:70]}")
            if not dry_run:
                merge_work(conn, keep["id"], drop["id"])
            merged += 1
        else:
            print(f"[REVIEW] {' / '.join(r['id'] for r in group)}  ({reason})")
            for record in group:
                print(f"         {record['year']} | {(record['title'] or '')[:70]}")
            if not dry_run and len(group) == 2:
                queue_for_review(conn, group[0], group[1], reason)
            queued += 1

    if not dry_run:
        conn.commit()

    verb = "Would merge" if dry_run else "Merged"
    print(f"\n{len(groups)} same-DOI group(s): {verb} {merged}, queued {queued} for review.")
    if queued:
        print("Review the queue in the admin UI (Curation tab) or via /api/curation/duplicates.")
    return {"groups": len(groups), "merged": merged, "queued": queued}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="Report only, change nothing")
    parser.add_argument("--db", default=str(DB_PATH), help="Database path")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        resolve(conn, dry_run=args.dry_run)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
