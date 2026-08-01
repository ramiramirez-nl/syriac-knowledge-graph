"""Generate notifications for users who have claimed an author profile.

This closes the last open Phase 3 item in PLAN.md: "alerts for new
publications/researchers intersecting with your work".

Three signals, all derived from data the pipeline already produces:

  1. new_work      — a work was added listing the claimed author, and the user
                     has not been told about it yet.
  2. neighbour     — a *new* work landed in one of the clusters the claimed
                     author publishes in (topical intersection).
  3. collaboration — the claimed author appears in `collaboration_candidates`,
                     i.e. someone works on similar topics without any existing
                     co-authorship or citation link.

Idempotency is enforced by `notifications.dedupe_key` (UNIQUE per user, see
scripts/migrate_notifications.py), so this script is safe to run on a schedule:
a second run over unchanged data inserts nothing.

Usage:
    uv run scripts/generate_notifications.py
    uv run scripts/generate_notifications.py --dry-run
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "syriac.db"

# Only surface collaboration hints above this similarity. The candidate table
# itself uses a lower bar (0.35); for a user-facing alert we want the stronger
# end of the list, since PLAN.md documents that low-scoring pairs still contain
# false positives from the title-similarity era.
COLLABORATION_ALERT_THRESHOLD = 0.55

# Cap per user per run so a first run on a large corpus cannot dump hundreds of
# rows into someone's inbox.
MAX_PER_USER_PER_KIND = 10


def truncate(text: str, limit: int = 90) -> str:
    text = (text or "(untitled)").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "\u2026"


def claimed_authors(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Approved author claims joined to the claiming user."""
    return conn.execute(
        """
        SELECT c.user_id, c.author_id, a.name AS author_name
        FROM user_claims c
        JOIN authors a ON a.id = c.author_id
        JOIN users u ON u.id = c.user_id
        WHERE c.status = 'approved'
        """
    ).fetchall()


def own_work_notifications(conn: sqlite3.Connection, claim: sqlite3.Row) -> list[dict]:
    """Works crediting the claimed author (signal 1)."""
    rows = conn.execute(
        """
        SELECT w.id, w.title, w.year
        FROM authorship au
        JOIN works w ON w.id = au.work_id
        WHERE au.author_id = ?
          AND w.status NOT IN ('deleted', 'excluded')
        ORDER BY COALESCE(w.year, 0) DESC
        LIMIT ?
        """,
        (claim["author_id"], MAX_PER_USER_PER_KIND),
    ).fetchall()

    return [
        {
            "user_id": claim["user_id"],
            "kind": "new_work",
            "dedupe_key": f"new_work:{row['id']}:{claim['author_id']}",
            "message": (
                f"A work listing you as an author is in the corpus: "
                f"\u201c{truncate(row['title'])}\u201d"
                + (f" ({row['year']})" if row["year"] else "")
            ),
            "link": f"#work={row['id']}",
        }
        for row in rows
    ]


def neighbour_work_notifications(conn: sqlite3.Connection, claim: sqlite3.Row) -> list[dict]:
    """New works in the clusters the claimed author publishes in (signal 2).

    This is the \"intersects with your work\" alert: same thematic cluster, not
    authored by them, and connected to one of their works by a similarity edge
    so the overlap is concrete rather than merely sharing a large cluster.
    """
    rows = conn.execute(
        """
        WITH mine AS (
            SELECT work_id FROM authorship WHERE author_id = ?
        ),
        my_clusters AS (
            SELECT DISTINCT cluster_id FROM work_clusters
            WHERE work_id IN (SELECT work_id FROM mine)
        ),
        neighbours AS (
            SELECT work_id_b AS other FROM similarity_edges
              WHERE work_id_a IN (SELECT work_id FROM mine)
            UNION
            SELECT work_id_a AS other FROM similarity_edges
              WHERE work_id_b IN (SELECT work_id FROM mine)
        )
        SELECT w.id, w.title, w.year, cl.top_terms
        FROM neighbours n
        JOIN works w ON w.id = n.other
        JOIN work_clusters wc ON wc.work_id = w.id
        JOIN clusters cl ON cl.cluster_id = wc.cluster_id
        WHERE w.id NOT IN (SELECT work_id FROM mine)
          AND wc.cluster_id IN (SELECT cluster_id FROM my_clusters)
          AND w.status NOT IN ('deleted', 'excluded')
        ORDER BY COALESCE(w.year, 0) DESC, w.cited_by_count DESC
        LIMIT ?
        """,
        (claim["author_id"], MAX_PER_USER_PER_KIND),
    ).fetchall()

    notifications = []
    for row in rows:
        topic = (row["top_terms"] or "").split(",")[0].strip()
        topic_hint = f" in your research area ({topic})" if topic else " in your research area"
        notifications.append(
            {
                "user_id": claim["user_id"],
                "kind": "neighbour",
                "dedupe_key": f"neighbour:{row['id']}:{claim['author_id']}",
                "message": (
                    f"A related work{topic_hint}: \u201c{truncate(row['title'])}\u201d"
                    + (f" ({row['year']})" if row["year"] else "")
                ),
                "link": f"#work={row['id']}",
            }
        )
    return notifications


def collaboration_notifications(conn: sqlite3.Connection, claim: sqlite3.Row) -> list[dict]:
    """Researchers on intersecting topics with no existing link (signal 3)."""
    rows = conn.execute(
        """
        SELECT other.id AS other_id, other.name AS other_name, cc.similarity
        FROM collaboration_candidates cc
        JOIN authors other
          ON other.id = CASE
               WHEN cc.author_id_a = :aid THEN cc.author_id_b
               ELSE cc.author_id_a
             END
        WHERE (cc.author_id_a = :aid OR cc.author_id_b = :aid)
          AND cc.similarity >= :threshold
        ORDER BY cc.similarity DESC
        LIMIT :limit
        """,
        {
            "aid": claim["author_id"],
            "threshold": COLLABORATION_ALERT_THRESHOLD,
            "limit": MAX_PER_USER_PER_KIND,
        },
    ).fetchall()

    return [
        {
            "user_id": claim["user_id"],
            "kind": "collaboration",
            # Order-independent key: the pair is the event, not its direction.
            "dedupe_key": "collaboration:"
            + ":".join(sorted([claim["author_id"], row["other_id"]])),
            "message": (
                f"{row['other_name']} works on topics close to yours "
                f"(similarity {row['similarity']:.2f}) with no shared publication "
                f"or citation yet \u2014 a possible collaboration."
            ),
            "link": f"#author={row['other_id']}",
        }
        for row in rows
    ]


GENERATORS = (own_work_notifications, neighbour_work_notifications, collaboration_notifications)


def generate(conn: sqlite3.Connection, dry_run: bool = False) -> dict:
    """Build and store notifications. Returns a per-kind count of new rows."""
    claims = claimed_authors(conn)
    if not claims:
        print(
            "No approved author claims found \u2014 nothing to notify.\n"
            "Users claim a profile via POST /api/users/claim (see site/profile.html)."
        )
        return {}

    pending: list[dict] = []
    for claim in claims:
        for generator in GENERATORS:
            pending.extend(generator(conn, claim))

    inserted = {"new_work": 0, "neighbour": 0, "collaboration": 0}
    skipped = 0

    for item in pending:
        if dry_run:
            exists = conn.execute(
                "SELECT 1 FROM notifications WHERE user_id = ? AND dedupe_key = ?",
                (item["user_id"], item["dedupe_key"]),
            ).fetchone()
            if exists:
                skipped += 1
            else:
                inserted[item["kind"]] += 1
            continue

        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO notifications
                (user_id, message, kind, dedupe_key, link)
            VALUES (:user_id, :message, :kind, :dedupe_key, :link)
            """,
            item,
        )
        if cursor.rowcount:
            inserted[item["kind"]] += 1
        else:
            skipped += 1

    if not dry_run:
        conn.commit()

    prefix = "Would create" if dry_run else "Created"
    total = sum(inserted.values())
    print(f"{prefix} {total} notification(s) for {len(claims)} claimed profile(s).")
    for kind, count in inserted.items():
        print(f"  {kind:<14} {count}")
    print(f"  already present {skipped} (deduplicated)")
    return inserted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would be created, write nothing"
    )
    parser.add_argument(
        "--db", default=str(DB_PATH), help="Database path (default: data/syriac.db)"
    )
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        generate(conn, dry_run=args.dry_run)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
