"""Tests for the same-DOI duplicate resolver (scripts/resolve_duplicates.py).

The risk this guards against is over-merging: distinct editions and volumes
share a DOI in this corpus, and merging them destroys real records.

Usage:
    uv run python -m unittest tests.test_resolve_duplicates -v
"""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

_spec = importlib.util.spec_from_file_location(
    "resolve_duplicates", ROOT / "scripts" / "resolve_duplicates.py"
)
rd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rd)

SCHEMA = """
CREATE TABLE works (
    id TEXT PRIMARY KEY, doi TEXT, title TEXT, year INTEGER, venue TEXT,
    work_type TEXT, cited_by_count INTEGER DEFAULT 0,
    source TEXT DEFAULT 'openalex', status TEXT DEFAULT 'auto'
);
CREATE TABLE authors (id TEXT PRIMARY KEY, name TEXT);
CREATE TABLE authorship (
    work_id TEXT, author_id TEXT, author_position TEXT,
    PRIMARY KEY (work_id, author_id)
);
CREATE TABLE citations (
    citing_work_id TEXT, cited_work_id TEXT,
    PRIMARY KEY (citing_work_id, cited_work_id)
);
CREATE TABLE work_references (
    work_id TEXT, referenced_work_id TEXT,
    PRIMARY KEY (work_id, referenced_work_id)
);
CREATE TABLE similarity_edges (
    work_id_a TEXT, work_id_b TEXT, weight REAL,
    PRIMARY KEY (work_id_a, work_id_b)
);
CREATE TABLE work_clusters (work_id TEXT PRIMARY KEY, cluster_id INTEGER);
CREATE TABLE manuscript_details (work_id TEXT PRIMARY KEY, language TEXT);
"""


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def add_work(conn, wid, doi, title, year, cited=0, venue=None, status="auto"):
    conn.execute(
        "INSERT INTO works (id, doi, title, year, venue, cited_by_count, status)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (wid, doi, title, year, venue, cited, status),
    )


class TitleVariantTests(unittest.TestCase):
    def test_subtitle_variant_is_recognised(self):
        self.assertTrue(
            rd.titles_are_variants("The Syriac Dot", "The Syriac Dot: A Short History")
        )

    def test_identical_titles_are_variants(self):
        self.assertTrue(rd.titles_are_variants("Syriac Grammar", "syriac  grammar!"))

    def test_different_prefix_is_not_a_variant(self):
        self.assertFalse(
            rd.titles_are_variants("Syriac Grammar", "Elements of Syriac Grammar")
        )

    def test_word_boundary_is_required(self):
        self.assertFalse(rd.titles_are_variants("The Syriac Dot", "The Syriac Dotted Text"))


class ClassificationTests(unittest.TestCase):
    def group(self, *rows):
        conn = make_conn()
        for row in rows:
            add_work(conn, *row)
        return conn.execute(
            "SELECT id, title, year, venue, cited_by_count FROM works ORDER BY id"
        ).fetchall()

    def test_subtitle_variant_is_auto(self):
        group = self.group(
            ("W1", "10.1/x", "The Syriac Dot", 2015),
            ("W2", "10.1/x", "The Syriac Dot: A Short History", 2015),
        )
        self.assertEqual(rd.classify(group)[0], "auto")

    def test_edition_marker_forces_manual_review(self):
        group = self.group(
            ("W1", "10.1/x", "The Bible in the Syriac Tradition", 2002),
            ("W2", "10.1/x", "The Bible in the Syriac Tradition (Third Edition)", 2021),
        )
        decision, reason = rd.classify(group)
        self.assertEqual(decision, "manual")
        self.assertIn("edition", reason.lower())

    def test_volume_marker_forces_manual_review(self):
        group = self.group(
            ("W1", "10.1/x", "Ancient Syriac Documents", 1989),
            ("W2", "10.1/x", "Ancient Syriac Documents Volume II", 1989),
        )
        self.assertEqual(rd.classify(group)[0], "manual")

    def test_large_year_gap_forces_manual_review(self):
        group = self.group(
            ("W1", "10.1/x", "Catalogue of the Syriac MSS", 1894),
            ("W2", "10.1/x", "Catalogue of the Syriac MSS", 2012),
        )
        decision, reason = rd.classify(group)
        self.assertEqual(decision, "manual")
        self.assertIn("118", reason)

    def test_group_larger_than_two_is_manual(self):
        group = self.group(
            ("W1", "10.1/x", "A Work", 2000),
            ("W2", "10.1/x", "A Work", 2000),
            ("W3", "10.1/x", "A Work", 2000),
        )
        self.assertEqual(rd.classify(group)[0], "manual")


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        # W1 is better cited but has the shorter title; W2 carries the subtitle.
        add_work(self.conn, "W1", "10.1/x", "Bethlehem's Syriac Christians", 2017, cited=14)
        add_work(
            self.conn, "W2", "10.1/x",
            "Bethlehem's Syriac Christians: Self, Nation and Church", 2017,
            cited=2, venue="Gorgias Press",
        )
        add_work(self.conn, "W9", None, "A Citing Work", 2020, cited=0)
        self.conn.executemany(
            "INSERT INTO citations (citing_work_id, cited_work_id) VALUES (?, ?)",
            [("W9", "W1"), ("W9", "W2")],
        )
        self.conn.execute("INSERT INTO authors (id, name) VALUES ('A1', 'Author One')")
        self.conn.execute(
            "INSERT INTO authorship (work_id, author_id, author_position)"
            " VALUES ('W2', 'A1', 'first')"
        )
        self.conn.execute(
            "INSERT INTO similarity_edges (work_id_a, work_id_b, weight) VALUES ('W1','W2',0.99)"
        )
        self.conn.executemany(
            "INSERT INTO work_clusters (work_id, cluster_id) VALUES (?, ?)",
            [("W1", 1), ("W2", 1)],
        )
        self.conn.commit()

    def test_dry_run_changes_nothing(self):
        rd.resolve(self.conn, dry_run=True)
        statuses = dict(self.conn.execute("SELECT id, status FROM works").fetchall())
        self.assertEqual(statuses["W1"], "auto")
        self.assertEqual(statuses["W2"], "auto")

    def test_merge_keeps_best_cited_record_and_richest_metadata(self):
        result = rd.resolve(self.conn)
        self.assertEqual(result["merged"], 1)

        survivor = self.conn.execute(
            "SELECT title, venue, cited_by_count, status FROM works WHERE id = 'W1'"
        ).fetchone()
        self.assertEqual(survivor["status"], "auto")
        self.assertIn("Self, Nation and Church", survivor["title"], "longer title wins")
        self.assertEqual(survivor["venue"], "Gorgias Press", "missing venue is filled in")
        self.assertEqual(survivor["cited_by_count"], 14)

        self.assertEqual(
            self.conn.execute("SELECT status FROM works WHERE id = 'W2'").fetchone()[0],
            "deleted",
            "the loser is soft-deleted, never dropped",
        )

    def test_merge_remaps_relations_and_leaves_no_self_links(self):
        rd.resolve(self.conn)
        citations = self.conn.execute(
            "SELECT citing_work_id, cited_work_id FROM citations"
        ).fetchall()
        self.assertEqual([tuple(r) for r in citations], [("W9", "W1")])
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM similarity_edges").fetchone()[0], 0
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT author_id FROM authorship WHERE work_id = 'W1'"
            ).fetchone()[0],
            "A1",
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM work_clusters WHERE work_id = 'W2'"
            ).fetchone()[0],
            0,
        )

    def test_mojibake_title_is_not_adopted(self):
        conn = make_conn()
        add_work(conn, "W1", "10.2/y", "Erica C. D. Hunter, Syrische Handschriften", 2018, cited=0)
        add_work(conn, "W2", "10.2/y", "Erica\ufffdC.\ufffdD. Hunter, Syrische Handschriften Teil 2", 2018)
        conn.commit()
        rd.resolve(conn)
        survivor_title = conn.execute(
            "SELECT title FROM works WHERE status = 'auto'"
        ).fetchone()[0]
        self.assertNotIn("\ufffd", survivor_title)


if __name__ == "__main__":
    unittest.main()
