"""Tests for the duplicate-queue triage rules (scripts/triage_duplicates.py).

The dangerous failure is over-merging: this corpus contains multi-volume sets,
chapter sequences and versioned datasets that share a title *and* an author.
Every case below was found in the real queue while building the rules.

Usage:
    uv run python -m unittest tests.test_triage -v
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
    "triage_duplicates", ROOT / "scripts" / "triage_duplicates.py"
)
td = importlib.util.module_from_spec(_spec)
sys.modules["triage_duplicates"] = td
_spec.loader.exec_module(td)

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
CREATE TABLE duplicate_candidates (
    work_id_a TEXT, work_id_b TEXT, score REAL, title_similarity REAL,
    same_doi INTEGER DEFAULT 0, year_difference INTEGER,
    venue_similarity REAL DEFAULT 0, reasons TEXT,
    review_status TEXT DEFAULT 'pending', curator_note TEXT, detected_at TEXT,
    PRIMARY KEY (work_id_a, work_id_b)
);
"""


class TriageCase(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def pair(self, a: dict, b: dict, authors_a=(), authors_b=()) -> sqlite3.Row:
        for work, authors in ((a, authors_a), (b, authors_b)):
            self.conn.execute(
                "INSERT INTO works (id, doi, title, year, venue, cited_by_count)"
                " VALUES (:id, :doi, :title, :year, :venue, :cited)",
                {"venue": None, "cited": 0, "doi": None, **work},
            )
            for author in authors:
                self.conn.execute(
                    "INSERT OR IGNORE INTO authors (id, name) VALUES (?, ?)", (author, author)
                )
                self.conn.execute(
                    "INSERT INTO authorship (work_id, author_id, author_position)"
                    " VALUES (?, ?, 'first')",
                    (work["id"], author),
                )
        self.conn.execute(
            "INSERT INTO duplicate_candidates (work_id_a, work_id_b, score, title_similarity)"
            " VALUES (?, ?, 0.95, 0.99)",
            (a["id"], b["id"]),
        )
        self.conn.commit()
        return self.conn.execute(td.PENDING_QUERY).fetchone()

    def decide(self, *args, **kwargs) -> tuple[str, str]:
        return td.decide(self.conn, self.pair(*args, **kwargs))


class SeriesTests(TriageCase):
    def test_different_parts_are_rejected(self):
        decision, reason = self.decide(
            {"id": "W1", "title": "Concordance to the Syriac New Testament. Part 1", "year": 2023},
            {"id": "W2", "title": "Concordance to the Syriac New Testament. Part 3", "year": 2023},
        )
        self.assertEqual(decision, "reject")
        self.assertIn("instalments", reason)

    def test_roman_numeral_volumes_are_rejected(self):
        decision, _ = self.decide(
            {"id": "W1", "title": "Peshitta Institute Communications V", "year": 1967},
            {"id": "W2", "title": "Peshitta Institute Communications VI", "year": 1967},
        )
        self.assertEqual(decision, "reject")


class DoiShapeTests(TriageCase):
    """Regression guards for the over-merges caught during development."""

    def test_chapter_sequence_in_one_book_is_rejected(self):
        # 'Ancient Syriac Documents' ch-117 vs ch-118: same book, different texts.
        decision, reason = self.decide(
            {"id": "W1", "title": "Ancient Syriac Documents", "year": 1989,
             "doi": "https://doi.org/10.5040/9780567697141.ch-117"},
            {"id": "W2", "title": "Ancient Syriac Documents", "year": 1989,
             "doi": "https://doi.org/10.5040/9780567697141.ch-118"},
            authors_a=("A1",), authors_b=("A1",),
        )
        self.assertEqual(decision, "reject")
        self.assertIn("parts/volumes", reason)

    def test_per_volume_isbns_are_rejected(self):
        # 'The Works of St. Ephrem the Syrian': one ISBN per volume.
        decision, _ = self.decide(
            {"id": "W1", "title": "The Works of St. Ephrem the Syrian", "year": 2010,
             "doi": "https://doi.org/10.31826/9781463223427"},
            {"id": "W2", "title": "The Works of St. Ephrem the Syrian", "year": 2010,
             "doi": "https://doi.org/10.31826/9781463223434"},
            authors_a=("A1",), authors_b=("A1",),
        )
        self.assertEqual(decision, "reject")

    def test_container_and_its_subrecord_are_rejected(self):
        decision, _ = self.decide(
            {"id": "W1", "title": "The Lighthouse of the Syriac Church", "year": 2010,
             "doi": "https://doi.org/10.31826/9781463217945"},
            {"id": "W2", "title": "The Lighthouse of the Syriac Church", "year": 2010,
             "doi": "https://doi.org/10.31826/9781463217945-001"},
        )
        self.assertEqual(decision, "reject")

    def test_zenodo_versions_are_rejected(self):
        # Zenodo mints a new DOI per dataset version; both are real records.
        decision, _ = self.decide(
            {"id": "W1", "title": "Text-Fabric dataset of the Syriac Corpus", "year": 2025,
             "doi": "https://doi.org/10.5281/zenodo.17911466"},
            {"id": "W2", "title": "Text-Fabric dataset of the Syriac Corpus", "year": 2026,
             "doi": "https://doi.org/10.5281/zenodo.19608412"},
            authors_a=("A1",), authors_b=("A1",),
        )
        self.assertEqual(decision, "reject")

    def test_two_indexes_of_one_article_still_merge(self):
        # Brill and JSTOR both index the same 1984 article: a genuine duplicate.
        decision, _ = self.decide(
            {"id": "W1", "title": "Some Syriac Excerpts from Greek Collections", "year": 1984,
             "doi": "https://doi.org/10.1163/157007284x00105"},
            {"id": "W2", "title": "Some Syriac Excerpts From Greek Collections", "year": 1984,
             "doi": "https://doi.org/10.2307/1583533"},
            authors_a=("A1",), authors_b=("A1",),
        )
        self.assertEqual(decision, "merge")


class AuthorshipTests(TriageCase):
    def test_identical_title_with_disjoint_authors_is_rejected(self):
        # Seven 1923 review articles share the title 'HISTORY OF SYRIAC LITERATURE'.
        decision, reason = self.decide(
            {"id": "W1", "title": "History of Syriac Literature", "year": 1923,
             "doi": "https://doi.org/10.1093/jts/os-xxiv.94.211"},
            {"id": "W2", "title": "History of Syriac Literature", "year": 1923,
             "doi": "https://doi.org/10.1093/jts/os-xxiv.94.200-b"},
            authors_a=("Oman",), authors_b=("Burkitt",),
        )
        self.assertEqual(decision, "reject")
        self.assertIn("no author in common", reason)

    def test_generic_title_without_authors_goes_to_review(self):
        decision, reason = self.decide(
            {"id": "W1", "title": "Ephrem the Syrian", "year": 2017,
             "doi": "https://doi.org/10.2307/j.ctt1kgqtbp.12"},
            {"id": "W2", "title": "Ephrem the Syrian", "year": 2017,
             "doi": "https://doi.org/10.5040/9780809171187"},
        )
        self.assertEqual(decision, "review")
        self.assertIn("too generic", reason)

    def test_disagreeing_venues_without_authors_go_to_review(self):
        decision, reason = self.decide(
            {"id": "W1", "title": "A Distinctive Long Syriac Title Here", "year": 2010,
             "venue": "Journal A", "doi": "https://doi.org/10.1/a"},
            {"id": "W2", "title": "A Distinctive Long Syriac Title Here", "year": 2010,
             "venue": "Journal B", "doi": "https://doi.org/10.2/b"},
        )
        self.assertEqual(decision, "review")
        self.assertIn("venues disagree", reason)

    def test_distinctive_title_same_venue_merges(self):
        decision, _ = self.decide(
            {"id": "W1", "title": "The Judaeo-Syriac Version of Bel and the Dragon", "year": 2016,
             "venue": "Mediterranean Language Review", "doi": "https://doi.org/10.13173/a"},
            {"id": "W2", "title": "The Judaeo-Syriac Version of Bel and the Dragon", "year": 2016,
             "venue": "Mediterranean Language Review", "doi": "https://doi.org/10.13173/b"},
        )
        self.assertEqual(decision, "merge")


class YearAndTitleTests(TriageCase):
    def test_reprint_gap_goes_to_review(self):
        decision, reason = self.decide(
            {"id": "W1", "title": "Catalogue of the Syriac MSS", "year": 1894},
            {"id": "W2", "title": "Catalogue of the Syriac MSS", "year": 2012},
            authors_a=("A1",), authors_b=("A1",),
        )
        self.assertEqual(decision, "review")
        self.assertIn("118 years", reason)

    def test_reversed_titles_go_to_review(self):
        # 'Greek-Syriac Index' vs 'Syriac-Greek Index' are different indexes.
        decision, _ = self.decide(
            {"id": "W1", "title": "Greek-Syriac Index", "year": 2009},
            {"id": "W2", "title": "Syriac-Greek Index", "year": 2009},
            authors_a=("A1",), authors_b=("A1",),
        )
        self.assertEqual(decision, "review")


class ApplyTests(TriageCase):
    def test_dry_run_leaves_the_queue_untouched(self):
        self.pair(
            {"id": "W1", "title": "Some Distinctive Syriac Article Title", "year": 1984,
             "doi": "https://doi.org/10.1163/a", "cited": 5},
            {"id": "W2", "title": "Some Distinctive Syriac Article Title", "year": 1984,
             "doi": "https://doi.org/10.2307/b"},
            authors_a=("A1",), authors_b=("A1",),
        )
        td.triage(self.conn, apply=False, merge_only=False, report=False)
        statuses = {r[0] for r in self.conn.execute("SELECT review_status FROM duplicate_candidates")}
        self.assertEqual(statuses, {"pending"})

    def test_apply_merges_and_records_the_decision(self):
        self.pair(
            {"id": "W1", "title": "Some Distinctive Syriac Article Title", "year": 1984,
             "doi": "https://doi.org/10.1163/a", "cited": 5},
            {"id": "W2", "title": "Some Distinctive Syriac Article Title", "year": 1984,
             "doi": "https://doi.org/10.2307/b"},
            authors_a=("A1",), authors_b=("A1",),
        )
        td.triage(self.conn, apply=True, merge_only=False, report=False)
        row = self.conn.execute(
            "SELECT review_status, curator_note FROM duplicate_candidates"
        ).fetchone()
        self.assertEqual(row["review_status"], "merged")
        self.assertIn("kept W1", row["curator_note"])
        self.assertEqual(
            self.conn.execute("SELECT status FROM works WHERE id = 'W2'").fetchone()[0],
            "deleted",
        )

    def test_merge_only_leaves_rejects_pending(self):
        self.pair(
            {"id": "W1", "title": "Concordance. Part 1", "year": 2023},
            {"id": "W2", "title": "Concordance. Part 2", "year": 2023},
        )
        td.triage(self.conn, apply=True, merge_only=True, report=False)
        self.assertEqual(
            self.conn.execute("SELECT review_status FROM duplicate_candidates").fetchone()[0],
            "pending",
        )

    def test_stale_candidates_are_closed(self):
        self.pair(
            {"id": "W1", "title": "Already Handled Elsewhere", "year": 2000},
            {"id": "W2", "title": "Already Handled Elsewhere", "year": 2000},
        )
        self.conn.execute("UPDATE works SET status = 'deleted' WHERE id = 'W2'")
        self.conn.commit()
        td.triage(self.conn, apply=True, merge_only=False, report=False)
        self.assertEqual(
            self.conn.execute("SELECT review_status FROM duplicate_candidates").fetchone()[0],
            "resolved",
        )


if __name__ == "__main__":
    unittest.main()
