"""Tests for the notification generator (scripts/generate_notifications.py).

Runs entirely on an in-memory database built to match the production schema,
so no fixture file or network access is needed.

Usage:
    uv run python -m unittest tests.test_notifications -v
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "generate_notifications", ROOT / "scripts" / "generate_notifications.py"
)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

SCHEMA = """
CREATE TABLE works (
    id TEXT PRIMARY KEY, doi TEXT, title TEXT, year INTEGER, venue TEXT,
    work_type TEXT, cited_by_count INTEGER DEFAULT 0,
    source TEXT DEFAULT 'openalex', status TEXT DEFAULT 'auto'
);
CREATE TABLE authors (id TEXT PRIMARY KEY, name TEXT);
CREATE TABLE authorship (work_id TEXT, author_id TEXT, author_position TEXT);
CREATE TABLE similarity_edges (
    work_id_a TEXT, work_id_b TEXT, weight REAL,
    PRIMARY KEY (work_id_a, work_id_b)
);
CREATE TABLE work_clusters (work_id TEXT PRIMARY KEY, cluster_id INTEGER);
CREATE TABLE clusters (cluster_id INTEGER PRIMARY KEY, size INTEGER, top_terms TEXT);
CREATE TABLE collaboration_candidates (
    author_id_a TEXT, author_id_b TEXT, similarity REAL
);
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE,
    hashed_password TEXT, role TEXT DEFAULT 'user'
);
CREATE TABLE user_claims (user_id INTEGER, author_id TEXT, status TEXT);
CREATE TABLE notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, message TEXT,
    is_read INTEGER DEFAULT 0, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    kind TEXT DEFAULT 'general', dedupe_key TEXT, link TEXT
);
CREATE UNIQUE INDEX idx_notifications_dedupe
    ON notifications (user_id, dedupe_key) WHERE dedupe_key IS NOT NULL;
"""


def build_db() -> sqlite3.Connection:
    """A claimed author (A1) with one own work, one topical neighbour, one
    excluded work, and one strong collaboration candidate."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT INTO works (id, title, year, status) VALUES (?, ?, ?, ?)",
        [
            ("W1", "My Own Study of Ephrem", 2020, "auto"),
            ("W2", "A Neighbouring Study of Ephrem", 2026, "auto"),
            ("W3", "A Deleted Neighbour", 2026, "deleted"),
            ("W4", "Unrelated Work In Another Cluster", 2026, "auto"),
        ],
    )
    conn.executemany(
        "INSERT INTO authors (id, name) VALUES (?, ?)",
        [("A1", "Claimed Person"), ("A2", "Unaware Colleague"), ("A3", "Weak Match")],
    )
    conn.executemany(
        "INSERT INTO authorship (work_id, author_id, author_position) VALUES (?, ?, 'first')",
        [("W1", "A1"), ("W2", "A2"), ("W3", "A2"), ("W4", "A3")],
    )
    conn.executemany(
        "INSERT INTO similarity_edges (work_id_a, work_id_b, weight) VALUES (?, ?, 0.8)",
        [("W1", "W2"), ("W1", "W3"), ("W1", "W4")],
    )
    conn.executemany(
        "INSERT INTO work_clusters (work_id, cluster_id) VALUES (?, ?)",
        [("W1", 1), ("W2", 1), ("W3", 1), ("W4", 2)],
    )
    conn.executemany(
        "INSERT INTO clusters (cluster_id, size, top_terms) VALUES (?, ?, ?)",
        [(1, 3, "ephrem, syriac"), (2, 1, "unrelated")],
    )
    conn.executemany(
        "INSERT INTO collaboration_candidates (author_id_a, author_id_b, similarity)"
        " VALUES (?, ?, ?)",
        [("A1", "A2", 0.91), ("A1", "A3", 0.40)],  # 0.40 is below the alert bar
    )
    conn.execute(
        "INSERT INTO users (id, email, hashed_password, role) VALUES (1, 'u@x.org', 'h', 'user')"
    )
    conn.commit()
    return conn


def claim(conn: sqlite3.Connection, status: str = "approved") -> None:
    conn.execute(
        "INSERT INTO user_claims (user_id, author_id, status) VALUES (1, 'A1', ?)", (status,)
    )
    conn.commit()


def kinds(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        row["kind"]: row["n"]
        for row in conn.execute("SELECT kind, COUNT(*) n FROM notifications GROUP BY kind")
    }


class NoClaimTests(unittest.TestCase):
    def test_without_claims_nothing_is_generated(self):
        conn = build_db()
        gen.generate(conn)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0], 0)

    def test_pending_claim_is_ignored(self):
        conn = build_db()
        claim(conn, status="pending")
        gen.generate(conn)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0], 0)


class SignalTests(unittest.TestCase):
    def setUp(self):
        self.conn = build_db()
        claim(self.conn)

    def test_all_three_signals_fire_once_each(self):
        gen.generate(self.conn)
        self.assertEqual(kinds(self.conn), {"new_work": 1, "neighbour": 1, "collaboration": 1})

    def test_own_work_notification_points_at_the_work(self):
        gen.generate(self.conn)
        row = self.conn.execute(
            "SELECT message, link FROM notifications WHERE kind = 'new_work'"
        ).fetchone()
        self.assertIn("My Own Study of Ephrem", row["message"])
        self.assertEqual(row["link"], "#work=W1")

    def test_neighbour_excludes_deleted_and_other_clusters(self):
        gen.generate(self.conn)
        links = {
            r["link"]
            for r in self.conn.execute("SELECT link FROM notifications WHERE kind = 'neighbour'")
        }
        self.assertEqual(links, {"#work=W2"})
        self.assertNotIn("#work=W3", links)  # deleted
        self.assertNotIn("#work=W4", links)  # different cluster

    def test_weak_collaboration_candidate_is_not_reported(self):
        gen.generate(self.conn)
        messages = " ".join(
            r["message"]
            for r in self.conn.execute("SELECT message FROM notifications WHERE kind='collaboration'")
        )
        self.assertIn("Unaware Colleague", messages)
        self.assertNotIn("Weak Match", messages)

    def test_second_run_is_idempotent(self):
        gen.generate(self.conn)
        before = self.conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
        created = gen.generate(self.conn)
        after = self.conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
        self.assertEqual(before, after, "re-running must not duplicate notifications")
        self.assertEqual(sum(created.values()), 0)

    def test_dry_run_writes_nothing(self):
        gen.generate(self.conn, dry_run=True)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0], 0
        )

    def test_collaboration_dedupe_key_is_order_independent(self):
        gen.generate(self.conn)
        key = self.conn.execute(
            "SELECT dedupe_key FROM notifications WHERE kind = 'collaboration'"
        ).fetchone()["dedupe_key"]
        # Reversing the stored pair must not produce a second notification.
        self.conn.execute("DELETE FROM collaboration_candidates")
        self.conn.execute(
            "INSERT INTO collaboration_candidates VALUES ('A2', 'A1', 0.91)"
        )
        self.conn.commit()
        gen.generate(self.conn)
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM notifications WHERE dedupe_key = ?", (key,)
            ).fetchone()[0],
            1,
        )


if __name__ == "__main__":
    unittest.main()
