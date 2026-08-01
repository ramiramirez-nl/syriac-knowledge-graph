"""Triage the duplicate_candidates queue so a curator reviews dozens, not ~900.

find_duplicates.py scores pairs but deliberately decides nothing. Reviewing the
whole queue by hand is impractical, and most of it does not need judgement — the
rows fall into a few mechanical patterns:

  * different volumes of one series ("...Part 1" vs "...Part 3", "Peshitta
    Institute Communications V" vs "VI") — scored high because the titles are
    nearly identical, but they are definitively *different works*. Merging them
    would destroy real records.
  * byte-identical titles, same year, compatible authorship — the classic
    OpenAlex double-index. Safe to merge.
  * identical titles but disjoint author sets — usually a shared generic title
    ("Ephrem the Syrian") by different scholars. Safe to reject.

Everything that does not match a rule cleanly stays `pending` for a human.

Nothing is deleted: merges soft-delete the loser (status='deleted'), rejects
only set review_status='rejected' on the candidate row.

Usage:
    uv run scripts/triage_duplicates.py --dry-run       # report only
    uv run scripts/triage_duplicates.py --report        # per-decision samples
    uv run scripts/triage_duplicates.py --apply         # merge + reject
    uv run scripts/triage_duplicates.py --apply --merge-only
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
import unicodedata
from collections import Counter
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
DB_PATH = ROOT / "data" / "syriac.db"

from resolve_duplicates import has_mojibake, merge_work  # noqa: E402

# Volume/part/fascicle markers. Two titles that differ only inside one of these
# are different instalments of one series, never duplicates of each other.
SERIES_MARKER = re.compile(
    r"\b(part|pt|vol|volume|tome|book|bk|no|nr|fasc\w*|band|teil|heft|section)\.?\s*"
    r"([0-9]{1,3}|[ivxlc]{1,6})\b",
    re.IGNORECASE,
)

# Same title + this far apart in time is a reprint/reissue, not a double index.
MAX_MERGE_YEAR_GAP = 1

# A DOI suffix that enumerates a part of a larger publication: '...-001',
# '.ch-118', '.0001'. Two records whose DOIs share a stem but differ only in
# such a counter are *sibling chapters/volumes of one work*, not duplicates.
DOI_SEQUENCE_SUFFIX = re.compile(r"[.\-_](?:ch[.\-_]?)?0*\d{1,4}$", re.IGNORECASE)

# Publisher stems where consecutive identifiers mean consecutive volumes rather
# than a re-index of the same item (Gorgias assigns one ISBN per volume).
SEQUENTIAL_ISBN_STEM = re.compile(r"10\.31826/97814632\d{5}", re.IGNORECASE)

# Registrars that mint a *new* DOI per version or per physical object, so two
# DOIs under the same prefix are two distinct records even with one title:
#   10.5281  Zenodo   — one DOI per dataset version
#   10.25549 InscriptiFact — one DOI per photographed object
VERSIONED_DOI_PREFIXES = ("10.5281/", "10.25549/")

# A chapter-position suffix on an otherwise unrelated DOI ('...-030', '...-010').
# Two different books both having a chapter 10 is not a duplicate signal.
CHAPTER_POSITION_SUFFIX = re.compile(r"-0*\d{2,3}$")

# Below this many words a title carries too little information to identify a
# work on its own ('Ephrem the Syrian', 'Syriac Mysticism').
MIN_DISTINCTIVE_TITLE_WORDS = 5

# A bare instalment number at the end of a title, with no 'part'/'vol' keyword:
# 'Peshitta Institute Communications VI', 'Syriac Manuscripts 3'. 'I' is
# excluded because a trailing 'I' is far more often a pronoun or initial.
TRAILING_NUMERAL = re.compile(
    r"\b((?:[0-9]{1,3})|(?:x{0,3}(?:ix|iv|v?i{1,3}|vi{0,3}))|(?:xl|l|xc|c))\s*$",
    re.IGNORECASE,
)


def normalize(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "").casefold()
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def series_tokens(title: str | None) -> set[str]:
    """All volume markers in a title, normalized to 'part:3' form.

    Also catches a bare trailing numeral, which is how several series in this
    corpus are numbered ('Peshitta Institute Communications V' / '... VI').
    """
    text = title or ""
    tokens = {f"{m.group(1).lower()}:{m.group(2).lower()}" for m in SERIES_MARKER.finditer(text)}
    trailing = TRAILING_NUMERAL.search(text)
    if trailing:
        tokens.add(f"trailing:{trailing.group(1).lower()}")
    return tokens


def authors_of(conn: sqlite3.Connection, work_id: str) -> set[str]:
    return {
        row[0]
        for row in conn.execute("SELECT author_id FROM authorship WHERE work_id = ?", (work_id,))
    }


def normalize_doi(value: str | None) -> str:
    doi = (value or "").strip().casefold()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix) :]
    return doi.strip()


def dois_look_like_siblings(doi_a: str | None, doi_b: str | None) -> bool:
    """True when two DOIs enumerate parts of one publication.

    This is the difference between "the same article indexed twice" and "chapter
    117 and chapter 118 of the same book", which share a title in this corpus:

        10.5040/9780567697141.ch-117  vs  ...ch-118   -> siblings
        10.31826/9781463217945        vs  ...-001     -> siblings
        10.31826/9781463223427        vs  ...3434     -> siblings (per-volume ISBN)
        10.2307/1517291               vs  10.1163/... -> genuinely two indexes
    """
    a, b = normalize_doi(doi_a), normalize_doi(doi_b)
    if not a or not b or a == b:
        return False

    # One DOI is the other plus an enumerating suffix.
    for long, short in ((a, b), (b, a)):
        if long.startswith(short) and DOI_SEQUENCE_SUFFIX.search(long[len(short) :] or long):
            return True

    stem_a, stem_b = DOI_SEQUENCE_SUFFIX.sub("", a), DOI_SEQUENCE_SUFFIX.sub("", b)
    if stem_a and stem_a == stem_b and a != b:
        return True

    # Consecutive per-volume ISBNs from the same publisher block.
    if SEQUENTIAL_ISBN_STEM.fullmatch(a) and SEQUENTIAL_ISBN_STEM.fullmatch(b):
        return True

    # Registrars that mint one DOI per version/object.
    for prefix in VERSIONED_DOI_PREFIXES:
        if a.startswith(prefix) and b.startswith(prefix):
            return True

    # Both carry a chapter-position suffix but sit in different containers:
    # chapter 10 of book X and chapter 10 of book Y are not the same chapter.
    if CHAPTER_POSITION_SUFFIX.search(a) and CHAPTER_POSITION_SUFFIX.search(b):
        if CHAPTER_POSITION_SUFFIX.sub("", a) != CHAPTER_POSITION_SUFFIX.sub("", b):
            return True

    # One side is a chapter inside a container, the other is not: a chapter and
    # a standalone record are different granularities, not duplicates.
    if bool(CHAPTER_POSITION_SUFFIX.search(a)) != bool(CHAPTER_POSITION_SUFFIX.search(b)):
        return True

    return False


def decide(conn: sqlite3.Connection, row: sqlite3.Row) -> tuple[str, str]:
    """Return (decision, reason) for one candidate pair.

    decision is 'merge', 'reject' or 'review'.
    """
    title_a, title_b = row["title_a"] or "", row["title_b"] or ""
    norm_a, norm_b = normalize(title_a), normalize(title_b)

    # --- series/volume handling ------------------------------------------
    tokens_a, tokens_b = series_tokens(title_a), series_tokens(title_b)
    if tokens_a or tokens_b:
        if tokens_a != tokens_b:
            return "reject", "different instalments of the same series"
        if norm_a != norm_b:
            return "review", "same volume marker but the titles still differ"
        # identical title *including* the marker: falls through to the normal
        # duplicate rules below.

    # --- titles must be identical to decide automatically ------------------
    if norm_a != norm_b:
        return "review", "titles are similar but not identical"

    # --- year -------------------------------------------------------------
    year_a, year_b = row["year_a"], row["year_b"]
    if year_a is not None and year_b is not None:
        gap = abs(year_a - year_b)
        if gap > MAX_MERGE_YEAR_GAP:
            return "review", f"identical titles but {gap} years apart (reprint?)"

    # --- DOI shape --------------------------------------------------------
    # Must run before the authorship rules: multi-volume sets and chapter
    # sequences share a title *and* an author, so authorship cannot tell them
    # apart. Merging them would silently destroy real records.
    if dois_look_like_siblings(row["doi_a"], row["doi_b"]):
        return "reject", "DOIs enumerate parts/volumes of one publication"

    # --- authorship -------------------------------------------------------
    authors_a = authors_of(conn, row["work_id_a"])
    authors_b = authors_of(conn, row["work_id_b"])
    if authors_a and authors_b and not (authors_a & authors_b):
        # A generic title like "Ephrem the Syrian" is written by many people;
        # identical title + no shared author means different works.
        return "reject", "identical title but no author in common"

    if authors_a and authors_b:
        return "merge", "identical title, same year, shared authorship"

    # Authorship missing on one side removes the strongest confirmation, and a
    # generic title ('Ephrem the Syrian', 'Syriac Mysticism') is often a chapter
    # heading reused across unrelated volumes. Require the venue to agree, or a
    # title distinctive enough that coincidence is implausible.
    venue_a, venue_b = normalize(row["venue_a"]), normalize(row["venue_b"])
    if venue_a and venue_b and venue_a != venue_b:
        return "review", "authorship missing on one side and venues disagree"
    if len(norm_a.split()) < MIN_DISTINCTIVE_TITLE_WORDS:
        return "review", "authorship missing on one side and the title is too generic"
    return "merge", "identical distinctive title, same year, same venue"


def pick_survivor(row: sqlite3.Row) -> tuple[str, str]:
    """Keep the better record: clean title, then citations, then richer metadata."""
    a = (
        not has_mojibake(row["title_a"]),
        row["cited_a"] or 0,
        row["venue_a"] is not None,
        len(row["title_a"] or ""),
        row["work_id_a"],
    )
    b = (
        not has_mojibake(row["title_b"]),
        row["cited_b"] or 0,
        row["venue_b"] is not None,
        len(row["title_b"] or ""),
        row["work_id_b"],
    )
    return (
        (row["work_id_a"], row["work_id_b"]) if a >= b else (row["work_id_b"], row["work_id_a"])
    )


PENDING_QUERY = """
    SELECT d.work_id_a, d.work_id_b, d.score, d.same_doi,
           a.title AS title_a, a.year AS year_a, a.venue AS venue_a,
           a.cited_by_count AS cited_a, a.doi AS doi_a,
           b.title AS title_b, b.year AS year_b, b.venue AS venue_b,
           b.cited_by_count AS cited_b, b.doi AS doi_b
    FROM duplicate_candidates d
    JOIN works a ON a.id = d.work_id_a
    JOIN works b ON b.id = d.work_id_b
    WHERE d.review_status = 'pending'
      AND a.status NOT IN ('deleted', 'excluded')
      AND b.status NOT IN ('deleted', 'excluded')
    ORDER BY d.score DESC
"""


def close_stale(conn: sqlite3.Connection) -> int:
    """Retire candidates whose works were already merged or excluded elsewhere."""
    cursor = conn.execute(
        """
        UPDATE duplicate_candidates
        SET review_status = 'resolved',
            curator_note = COALESCE(curator_note, 'auto: one side already merged/excluded')
        WHERE review_status = 'pending'
          AND (
            work_id_a IN (SELECT id FROM works WHERE status IN ('deleted','excluded'))
            OR work_id_b IN (SELECT id FROM works WHERE status IN ('deleted','excluded'))
          )
        """
    )
    return cursor.rowcount


def triage(conn: sqlite3.Connection, apply: bool, merge_only: bool, report: bool) -> Counter:
    stale = close_stale(conn) if apply else 0
    if stale:
        print(f"Closed {stale} stale candidate(s) whose works were already resolved.\n")

    rows = conn.execute(PENDING_QUERY).fetchall()
    counts: Counter = Counter()
    reasons: Counter = Counter()
    samples: dict[str, list[str]] = {"merge": [], "reject": [], "review": []}

    for row in rows:
        decision, reason = decide(conn, row)
        counts[decision] += 1
        reasons[f"{decision}: {reason}"] += 1

        if len(samples[decision]) < 8:
            samples[decision].append(
                f"  [{row['score']:.3f}] {reason}\n"
                f"     A {row['year_a']}: {(row['title_a'] or '')[:70]}\n"
                f"     B {row['year_b']}: {(row['title_b'] or '')[:70]}"
            )

        if not apply:
            continue

        if decision == "merge":
            keep, drop = pick_survivor(row)
            merge_work(conn, keep, drop)
            conn.execute(
                """UPDATE duplicate_candidates
                   SET review_status = 'merged', curator_note = ?
                   WHERE work_id_a = ? AND work_id_b = ?""",
                (f"auto-triage: {reason} (kept {keep})", row["work_id_a"], row["work_id_b"]),
            )
        elif decision == "reject" and not merge_only:
            conn.execute(
                """UPDATE duplicate_candidates
                   SET review_status = 'rejected', curator_note = ?
                   WHERE work_id_a = ? AND work_id_b = ?""",
                (f"auto-triage: {reason}", row["work_id_a"], row["work_id_b"]),
            )

    if apply:
        conn.commit()

    if report:
        for decision in ("merge", "reject", "review"):
            print("=" * 72)
            print(f"{decision.upper()}  ({counts[decision]} pairs)")
            print("=" * 72)
            for sample in samples[decision]:
                print(sample)
            print()

    print("Decision breakdown:")
    for reason, count in reasons.most_common():
        print(f"  {count:>5}  {reason}")

    total = sum(counts.values())
    verb = "Applied" if apply else "Would apply"
    print(f"\n{total} live pending candidate(s).")
    print(f"  {verb}: {counts['merge']} merge, {counts['reject']} reject")
    print(f"  Left for a human: {counts['review']}")
    if apply:
        print("\nRe-run compute_analysis.py and export_json.py to refresh the graph.")
    return counts


def export_review_queue(conn: sqlite3.Connection, path: Path) -> int:
    """Dump the undecidable pairs to CSV so they can be reviewed in a spreadsheet.

    Sorted by reason then score, so identical judgement calls sit together and a
    curator can sweep a whole category at once instead of context-switching.
    """
    rows = conn.execute(PENDING_QUERY).fetchall()
    pending = []
    for row in rows:
        decision, reason = decide(conn, row)
        if decision == "review":
            pending.append((reason, row))
    pending.sort(key=lambda item: (item[0], -item[1]["score"]))

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "reason", "score", "decision (fill in: merge/reject)",
                "id_a", "year_a", "title_a", "venue_a", "doi_a",
                "id_b", "year_b", "title_b", "venue_b", "doi_b",
            ]
        )
        for reason, row in pending:
            writer.writerow(
                [
                    reason, f"{row['score']:.3f}", "",
                    row["work_id_a"], row["year_a"], row["title_a"], row["venue_a"], row["doi_a"],
                    row["work_id_b"], row["year_b"], row["title_b"], row["venue_b"], row["doi_b"],
                ]
            )
    return len(pending)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--apply", action="store_true", help="Write the decisions")
    group.add_argument("--dry-run", action="store_true", help="Report only (default)")
    parser.add_argument("--report", action="store_true", help="Print samples per decision")
    parser.add_argument(
        "--merge-only", action="store_true", help="Apply merges but leave rejects pending"
    )
    parser.add_argument("--db", default=str(DB_PATH), help="Database path")
    parser.add_argument(
        "--export-review",
        metavar="PATH",
        help="Write the pairs left for a human to a CSV for offline review",
    )
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        triage(conn, apply=args.apply, merge_only=args.merge_only, report=args.report)
        if args.export_review:
            written = export_review_queue(conn, Path(args.export_review))
            print(f"\nWrote {written} pair(s) needing human judgement to {args.export_review}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
