"""Merge duplicate author records in data/syriac.db.

OpenAlex creates separate author IDs for the same person when their name
appears differently across publications (e.g. "Sebastian P. Brock",
"S. P. Brock", "S. BROCK", "Sebastian Brock"). This script detects and
merges these duplicates by:

1. Grouping authors by normalized surname.
2. Within each surname group, comparing first names using initial-matching
   heuristics (e.g. "S." matches "Sebastian", "G." matches "George").
3. Picking the "canonical" record (the one with the most works or the
   longest/most complete name) and re-pointing all authorship records
   to it.
4. Deleting orphaned author records.

Usage:
    uv run scripts/merge_authors.py              # execute merge
    uv run scripts/merge_authors.py --dry-run     # preview only
"""

from __future__ import annotations

import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "syriac.db"


def normalize_surname(name: str) -> str:
    """Extract and normalize the surname (last word) from a full name."""
    parts = name.strip().split()
    if not parts:
        return ""
    surname = parts[-1]
    # Handle compound surnames like "Hugonnard-Roche"
    return surname.lower().strip(".,;:")


def normalize_first(name: str) -> str:
    """Extract the first name / initials portion."""
    parts = name.strip().split()
    if len(parts) <= 1:
        return ""
    return " ".join(parts[:-1])


def initials_match(name_a: str, name_b: str) -> bool:
    """Check if two first-name strings could refer to the same person.
    
    Rules:
    - "S." matches "Sebastian" (initial matches full name starting with same letter)
    - "S. P." matches "Sebastian P."
    - "George A." matches "George Anton"
    - Case insensitive
    - "Sebastian" matches "Sebastian" (exact)
    """
    a = name_a.strip().lower()
    b = name_b.strip().lower()
    
    if not a or not b:
        return False
    
    # Tokenize into first name parts
    parts_a = re.split(r"[\s.]+", a)
    parts_a = [p.strip(",;:") for p in parts_a if p.strip(",;:")]
    parts_b = re.split(r"[\s.]+", b)
    parts_b = [p.strip(",;:") for p in parts_b if p.strip(",;:")]
    
    if not parts_a or not parts_b:
        return False
    
    # Compare the shorter list against the longer
    shorter, longer = (parts_a, parts_b) if len(parts_a) <= len(parts_b) else (parts_b, parts_a)
    
    for i, s_part in enumerate(shorter):
        if i >= len(longer):
            break
        l_part = longer[i]
        
        # Exact match
        if s_part == l_part:
            continue
        # Initial match: "s" matches "sebastian"
        if len(s_part) == 1 and l_part.startswith(s_part):
            continue
        if len(l_part) == 1 and s_part.startswith(l_part):
            continue
        # No match at this position
        return False
    
    return True


def pick_canonical(authors: list[dict]) -> dict:
    """Pick the best canonical record from a group of duplicates.
    
    Prefers: most works > longest full name > alphabetically first ID.
    """
    return max(authors, key=lambda a: (a["work_count"], len(a["name"]), a["name"]))


def find_merge_groups(conn: sqlite3.Connection) -> list[list[dict]]:
    """Identify groups of author records that should be merged."""
    # Load all authors with their work counts
    rows = conn.execute("""
        SELECT a.id, a.name, COUNT(DISTINCT au.work_id) as work_count
        FROM authors a
        LEFT JOIN authorship au ON a.id = au.author_id
        GROUP BY a.id
    """).fetchall()
    
    authors = [{"id": r[0], "name": r[1], "work_count": r[2]} for r in rows]
    
    # Group by normalized surname
    by_surname: dict[str, list[dict]] = defaultdict(list)
    for a in authors:
        surname = normalize_surname(a["name"])
        if surname:
            by_surname[surname].append(a)
    
    merge_groups = []
    
    for surname, group in by_surname.items():
        if len(group) < 2:
            continue
        
        # Within each surname group, find clusters of matching first names
        merged_indices: set[int] = set()
        
        for i in range(len(group)):
            if i in merged_indices:
                continue
            
            cluster = [group[i]]
            first_i = normalize_first(group[i]["name"])
            
            for j in range(i + 1, len(group)):
                if j in merged_indices:
                    continue
                first_j = normalize_first(group[j]["name"])
                
                if initials_match(first_i, first_j):
                    cluster.append(group[j])
                    merged_indices.add(j)
            
            if len(cluster) > 1:
                merge_groups.append(cluster)
                merged_indices.add(i)
    
    return merge_groups


def execute_merge(conn: sqlite3.Connection, groups: list[list[dict]], dry_run: bool) -> None:
    """Merge each group of duplicates into a single canonical record."""
    total_merged = 0
    total_removed = 0
    
    for group in groups:
        canonical = pick_canonical(group)
        others = [a for a in group if a["id"] != canonical["id"]]
        
        if not others:
            continue
        
        other_ids = [a["id"] for a in others]
        total_merged += 1
        total_removed += len(others)
        
        if dry_run:
            names = ", ".join(f'"{a["name"]}" ({a["work_count"]}w)' for a in others)
            print(f"  MERGE: {names}  →  \"{canonical['name']}\" ({canonical['work_count']}w)")
            continue
        
        # Re-point authorship records to canonical
        for old_id in other_ids:
            # Check for conflicts: if canonical already has authorship for the same work
            conflicts = conn.execute("""
                SELECT work_id FROM authorship 
                WHERE author_id = ? AND work_id IN (
                    SELECT work_id FROM authorship WHERE author_id = ?
                )
            """, (old_id, canonical["id"])).fetchall()
            
            conflict_work_ids = {r[0] for r in conflicts}
            
            if conflict_work_ids:
                # Delete conflicting authorship rows (canonical already covers these)
                placeholders = ",".join("?" * len(conflict_work_ids))
                conn.execute(
                    f"DELETE FROM authorship WHERE author_id = ? AND work_id IN ({placeholders})",
                    [old_id] + list(conflict_work_ids)
                )
            
            # Move remaining authorship records
            conn.execute(
                "UPDATE authorship SET author_id = ? WHERE author_id = ?",
                (canonical["id"], old_id)
            )
            
            # Update collaboration_candidates if it exists
            try:
                # Delete rows that would create duplicates after update
                conn.execute(
                    "DELETE FROM collaboration_candidates WHERE author_id_a = ? OR author_id_b = ?",
                    (old_id, old_id)
                )
            except sqlite3.OperationalError:
                pass  # Table may not exist
            
            # Delete old author record
            conn.execute("DELETE FROM authors WHERE id = ?", (old_id,))
    
    if not dry_run:
        conn.commit()
    
    print(f"\n{'[DRY RUN] ' if dry_run else ''}Summary:")
    print(f"  Merge groups: {total_merged}")
    print(f"  Duplicate records removed: {total_removed}")
    
    if not dry_run:
        n_authors = conn.execute("SELECT COUNT(*) FROM authors").fetchone()[0]
        n_works = conn.execute("SELECT COUNT(*) FROM works").fetchone()[0]
        print(f"  Remaining: authors={n_authors} works={n_works}")


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    
    conn = sqlite3.connect(DB_PATH)
    
    print("Scanning for duplicate authors...")
    groups = find_merge_groups(conn)
    
    if not groups:
        print("No duplicate author groups found.")
        conn.close()
        return
    
    total_dupes = sum(len(g) - 1 for g in groups)
    print(f"Found {len(groups)} merge groups with {total_dupes} duplicate records.\n")
    
    execute_merge(conn, groups, dry_run)
    
    if not dry_run:
        print("\nNext: re-run `uv run scripts/compute_analysis.py` then `uv run scripts/export_json.py`.")
    
    conn.close()


if __name__ == "__main__":
    main()
