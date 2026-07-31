from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.check_data import check_database
from scripts.compute_analysis import is_review_like
from scripts.find_duplicates import detect_candidates, ensure_schema, normalize_doi, normalize_text


class NormalizationTests(unittest.TestCase):
    def test_text_normalization_ignores_case_punctuation_and_accents(self) -> None:
        self.assertEqual(normalize_text("Éphrem—The Syrian!"), "ephrem the syrian")

    def test_doi_normalization_removes_common_prefixes(self) -> None:
        self.assertEqual(normalize_doi("https://doi.org/10.1234/ABC "), "10.1234/abc")
        self.assertEqual(normalize_doi("doi:10.1234/ABC"), "10.1234/abc")


class ReviewDetectionTests(unittest.TestCase):
    def test_review_markers_are_detected(self) -> None:
        self.assertTrue(is_review_like("Review of Syriac Literature", "article"))
        self.assertTrue(is_review_like("A New Grammar (Book Review)", "article"))
        self.assertTrue(is_review_like("A Grammar. 182pp.", "article"))

    def test_ordinary_italicized_title_is_not_a_review(self) -> None:
        self.assertFalse(is_review_like("The Syriac <i>Life of Anthony</i>", "article"))


class DuplicateDetectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            """CREATE TABLE works (
                id TEXT PRIMARY KEY, doi TEXT, title TEXT, year INTEGER, venue TEXT
            )"""
        )
        self.rows = [
            ("W1", "10.1/example", "The Syriac Acts of Thomas", 2020, "Journal of Syriac Studies"),
            ("W2", "https://doi.org/10.1/EXAMPLE", "The Syriac Acts of Thomas", 2020, "Journal of Syriac Studies"),
            ("W3", None, "A Completely Different Publication", 1990, "Another Journal"),
        ]
        self.conn.executemany("INSERT INTO works VALUES (?, ?, ?, ?, ?)", self.rows)

    def tearDown(self) -> None:
        self.conn.close()

    def test_duplicate_doi_pair_is_detected(self) -> None:
        rows = list(self.conn.execute("SELECT * FROM works ORDER BY id"))
        candidates = detect_candidates(rows, threshold=0.86)
        pairs = {(row[0], row[1]) for row in candidates}
        self.assertIn(("W1", "W2"), pairs)
        self.assertNotIn(("W1", "W3"), pairs)

    def test_review_decision_survives_queue_refresh_schema(self) -> None:
        ensure_schema(self.conn)
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(duplicate_candidates)")}
        self.assertIn("review_status", columns)
        self.assertIn("curator_note", columns)


class IntegrityCheckTests(unittest.TestCase):
    def make_database(self) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE works (id TEXT PRIMARY KEY, doi TEXT, title TEXT, year INTEGER);
            CREATE TABLE authors (id TEXT PRIMARY KEY, name TEXT);
            CREATE TABLE authorship (work_id TEXT, author_id TEXT);
            CREATE TABLE citations (citing_work_id TEXT, cited_work_id TEXT);
            CREATE TABLE work_references (work_id TEXT, referenced_work_id TEXT);
            CREATE TABLE similarity_edges (work_id_a TEXT, work_id_b TEXT);
            CREATE TABLE work_clusters (work_id TEXT, cluster_id INTEGER);
            CREATE TABLE clusters (cluster_id INTEGER, size INTEGER);
            CREATE TABLE collaboration_candidates (author_id_a TEXT, author_id_b TEXT);
            INSERT INTO works VALUES ('W1', NULL, 'Example', 2020);
            INSERT INTO authors VALUES ('A1', 'Researcher');
            INSERT INTO authorship VALUES ('W1', 'A1');
            INSERT INTO work_clusters VALUES ('W1', 1);
            INSERT INTO clusters VALUES (1, 1);
            """
        )
        return conn

    def test_clean_minimal_database_has_no_errors(self) -> None:
        conn = self.make_database()
        results = check_database(conn)
        self.assertFalse([result for result in results if result.level == "ERROR"])
        conn.close()

    def test_self_citation_is_an_error(self) -> None:
        conn = self.make_database()
        conn.execute("INSERT INTO citations VALUES ('W1', 'W1')")
        results = check_database(conn)
        self.assertTrue(any(result.level == "ERROR" and "self-citations" in result.message for result in results))
        conn.close()


class LocalServerTests(unittest.TestCase):
    def test_main_help_is_available(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "main.py"), "--help"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("--no-browser", completed.stdout)

    def test_export_is_valid_json_with_meta(self) -> None:
        with (ROOT / "site" / "data.json").open(encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertIn("meta", data)
        self.assertGreater(data["meta"]["workCount"], 0)


if __name__ == "__main__":
    unittest.main()
