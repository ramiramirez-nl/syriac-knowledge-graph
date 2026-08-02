"""API-layer tests for the FastAPI backend.

Every test runs against a throwaway SQLite file built by `build_test_db()`,
never against data/syriac.db, so the suite is safe to run repeatedly and needs
no network access.

The app reads its database path at import time via api.database.DB_PATH, so the
fixture overrides the `get_db` dependency instead of touching the module global.

Usage:
    uv run python -m unittest tests.test_api -v
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# A deterministic secret keeps tokens valid across the whole test process and
# silences the "no SECRET_KEY" warning from api.auth.
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")

from fastapi.testclient import TestClient  # noqa: E402

from api.database import get_db  # noqa: E402
from api.main import app  # noqa: E402

SCHEMA = """
CREATE TABLE works (
    id TEXT PRIMARY KEY, doi TEXT, title TEXT, year INTEGER, venue TEXT,
    work_type TEXT, cited_by_count INTEGER DEFAULT 0,
    source TEXT DEFAULT 'openalex', status TEXT DEFAULT 'auto'
);
CREATE TABLE authors (
    id TEXT PRIMARY KEY, name TEXT, source TEXT DEFAULT 'openalex',
    status TEXT DEFAULT 'auto', bio TEXT, interests TEXT
);
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
    work_id_a TEXT, work_id_b TEXT, weight REAL, has_citation INTEGER,
    coupling REAL, cocitation REAL, tfidf REAL,
    PRIMARY KEY (work_id_a, work_id_b)
);
CREATE TABLE work_clusters (work_id TEXT PRIMARY KEY, cluster_id INTEGER);
CREATE TABLE clusters (cluster_id INTEGER PRIMARY KEY, size INTEGER, top_terms TEXT);
CREATE TABLE collaboration_candidates (
    author_id_a TEXT, author_id_b TEXT, similarity REAL,
    PRIMARY KEY (author_id_a, author_id_b)
);
CREATE TABLE manuscript_details (
    work_id TEXT PRIMARY KEY, language TEXT, date_composed TEXT,
    archive_location TEXT, shelfmark TEXT, incipit TEXT
);
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE,
    hashed_password TEXT, role TEXT DEFAULT 'user'
);
CREATE TABLE user_claims (
    user_id INTEGER, author_id TEXT, status TEXT DEFAULT 'pending'
);
CREATE TABLE pending_contributions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, type TEXT,
    payload TEXT, status TEXT DEFAULT 'pending',
    submitted_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, message TEXT,
    is_read INTEGER DEFAULT 0, created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    kind TEXT DEFAULT 'general', dedupe_key TEXT, link TEXT
);
CREATE UNIQUE INDEX idx_notifications_dedupe
    ON notifications (user_id, dedupe_key) WHERE dedupe_key IS NOT NULL;
"""


def build_test_db(path: Path) -> None:
    """Create a minimal but schema-faithful database with two linked works."""
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT INTO works (id, doi, title, year, venue, work_type, source, status)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("W1", "10.1/a", "Syriac Grammar", 1904, "Journal A", "book", "openalex", "auto"),
            ("W2", "10.1/a", "Syriac Grammar", 1904, "Journal A", "book", "openalex", "auto"),
            ("W3", None, "Peshitta Studies", 1990, "Journal B", "article", "openalex", "auto"),
        ],
    )
    conn.executemany(
        "INSERT INTO authors (id, name) VALUES (?, ?)",
        [("A1", "Theodor Noldeke"), ("A2", "Sebastian Brock")],
    )
    conn.executemany(
        "INSERT INTO authorship (work_id, author_id, author_position) VALUES (?, ?, ?)",
        [("W1", "A1", "first"), ("W2", "A2", "first"), ("W3", "A2", "first")],
    )
    # W3 cites both duplicates; after merging W2 into W1 this must collapse to
    # a single W3 -> W1 edge with no self-citation left behind.
    conn.executemany(
        "INSERT INTO citations (citing_work_id, cited_work_id) VALUES (?, ?)",
        [("W3", "W1"), ("W3", "W2")],
    )
    conn.execute(
        "INSERT INTO similarity_edges (work_id_a, work_id_b, weight, has_citation,"
        " coupling, cocitation, tfidf) VALUES ('W1', 'W2', 0.9, 1, 0.5, 0.2, 0.9)"
    )
    conn.executemany(
        "INSERT INTO work_clusters (work_id, cluster_id) VALUES (?, ?)",
        [("W1", 1), ("W2", 1), ("W3", 1)],
    )
    conn.execute("INSERT INTO clusters (cluster_id, size, top_terms) VALUES (1, 3, 'syriac')")

    # The recorded duplicate backlog that /api/curation/queue works through.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS duplicate_candidates (
            work_id_a TEXT, work_id_b TEXT, score REAL, title_similarity REAL,
            same_doi INTEGER DEFAULT 0, year_difference INTEGER,
            venue_similarity REAL DEFAULT 0, reasons TEXT,
            review_status TEXT DEFAULT 'pending', curator_note TEXT, detected_at TEXT,
            PRIMARY KEY (work_id_a, work_id_b)
        )
        """
    )
    conn.execute(
        "INSERT INTO duplicate_candidates (work_id_a, work_id_b, score, title_similarity,"
        " reasons, review_status) VALUES ('W1', 'W2', 0.95, 0.99, 'title=0.99', 'pending')"
    )
    conn.commit()
    conn.close()


class ApiTestCase(unittest.TestCase):
    """Base class wiring a fresh database into the app for each test."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"
        build_test_db(self.db_path)

        def override_get_db():
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
            finally:
                conn.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self._tmp.cleanup()

    def register(self, email: str, password: str = "pw-12345") -> str:
        resp = self.client.post(
            "/api/auth/register", json={"email": email, "password": password}
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()["access_token"]

    def auth(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}


class HealthTests(ApiTestCase):
    def test_healthz_is_public(self):
        resp = self.client.get("/healthz")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_status_endpoint_requires_admin(self):
        self.assertEqual(self.client.get("/api/status").status_code, 401)


class AuthTests(ApiTestCase):
    def test_first_user_becomes_admin_and_second_does_not(self):
        first = self.register("first@example.org")
        second = self.register("second@example.org")
        self.assertEqual(
            self.client.get("/api/status", headers=self.auth(first)).status_code, 200
        )
        self.assertEqual(
            self.client.get("/api/status", headers=self.auth(second)).status_code, 403
        )

    def test_duplicate_email_is_rejected(self):
        self.register("dup@example.org")
        resp = self.client.post(
            "/api/auth/register", json={"email": "dup@example.org", "password": "x"}
        )
        self.assertEqual(resp.status_code, 400)

    def test_login_rejects_wrong_password(self):
        self.register("user@example.org", "correct-horse")
        ok = self.client.post(
            "/api/auth/login",
            json={"email": "user@example.org", "password": "correct-horse"},
        )
        self.assertEqual(ok.status_code, 200, ok.text)
        bad = self.client.post(
            "/api/auth/login",
            json={"email": "user@example.org", "password": "wrong"},
        )
        self.assertEqual(bad.status_code, 401)

    def test_token_for_deleted_user_is_rejected(self):
        token = self.register("ghost@example.org")
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM users")
        conn.commit()
        conn.close()
        resp = self.client.get("/api/status", headers=self.auth(token))
        self.assertEqual(resp.status_code, 401)


class WorkWriteProtectionTests(ApiTestCase):
    """Every mutating works endpoint must be admin-only (regression guard for
    the security-hardening pass)."""

    def test_reads_are_public(self):
        resp = self.client.get("/api/works")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 3)

    def test_anonymous_writes_are_rejected(self):
        payload = {"title": "Anonymous injection"}
        self.assertEqual(self.client.post("/api/works", json=payload).status_code, 401)
        self.assertEqual(self.client.put("/api/works/W1", json=payload).status_code, 401)
        self.assertEqual(self.client.delete("/api/works/W1").status_code, 401)
        self.assertEqual(self.client.post("/api/works/W1/exclude").status_code, 401)
        self.assertEqual(
            self.client.post(
                "/api/works/merge", json={"primary_id": "W1", "secondary_id": "W2"}
            ).status_code,
            401,
        )

    def test_non_admin_writes_are_forbidden(self):
        self.register("admin@example.org")  # consumes the admin bootstrap slot
        member = self.register("member@example.org")
        resp = self.client.post(
            "/api/works", json={"title": "Member entry"}, headers=self.auth(member)
        )
        self.assertEqual(resp.status_code, 403)


class WorkLifecycleTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.register("admin@example.org")

    def test_create_update_and_soft_delete(self):
        created = self.client.post(
            "/api/works",
            json={"title": "Manual entry", "year": 2026, "authors": ["Jane Doe"]},
            headers=self.auth(self.admin),
        )
        self.assertEqual(created.status_code, 200, created.text)
        work_id = created.json()["id"]
        self.assertTrue(work_id.startswith("manual:"))
        self.assertEqual(created.json()["source"], "manual")

        updated = self.client.put(
            f"/api/works/{work_id}",
            json={"title": "Manual entry, revised"},
            headers=self.auth(self.admin),
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["title"], "Manual entry, revised")

        self.client.delete(f"/api/works/{work_id}", headers=self.auth(self.admin))
        listed = {w["id"] for w in self.client.get("/api/works").json()}
        self.assertNotIn(work_id, listed, "soft-deleted work must not be listed")

    def test_manuscript_details_round_trip(self):
        created = self.client.post(
            "/api/works",
            json={
                "title": "Undated codex",
                "work_type": "manuscript",
                "manuscript_details": {"language": "Syriac", "shelfmark": "Add. 12150"},
            },
            headers=self.auth(self.admin),
        )
        self.assertEqual(created.status_code, 200, created.text)
        details = created.json()["manuscript_details"]
        self.assertEqual(details["language"], "Syriac")
        self.assertEqual(details["shelfmark"], "Add. 12150")


class MergeWorksTests(ApiTestCase):
    """Merging is the highest-risk write: it rewrites six relation tables."""

    def setUp(self):
        super().setUp()
        self.admin = self.register("admin@example.org")

    def test_merge_remaps_relations_without_self_citations(self):
        resp = self.client.post(
            "/api/works/merge",
            json={"primary_id": "W1", "secondary_id": "W2"},
            headers=self.auth(self.admin),
        )
        self.assertEqual(resp.status_code, 200, resp.text)

        conn = sqlite3.connect(self.db_path)
        citations = conn.execute(
            "SELECT citing_work_id, cited_work_id FROM citations"
        ).fetchall()
        self.assertEqual(citations, [("W3", "W1")], "duplicate edges must collapse")
        self.assertEqual(
            conn.execute(
                "SELECT COUNT(*) FROM citations WHERE citing_work_id = cited_work_id"
            ).fetchone()[0],
            0,
            "merge must not leave self-citations behind",
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM similarity_edges").fetchone()[0],
            0,
            "the W1-W2 edge becomes a self-loop and must be dropped",
        )
        self.assertEqual(
            conn.execute("SELECT status FROM works WHERE id = 'W2'").fetchone()[0],
            "deleted",
        )
        authorship = conn.execute(
            "SELECT author_id FROM authorship WHERE work_id = 'W1' ORDER BY author_id"
        ).fetchall()
        self.assertEqual(authorship, [("A1",), ("A2",)], "authors must move to primary")
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM work_clusters WHERE work_id = 'W2'").fetchone()[0],
            0,
        )
        conn.close()


class ContributionWorkflowTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.register("admin@example.org")
        self.member = self.register("member@example.org")

    def test_member_submits_and_admin_approves(self):
        submitted = self.client.post(
            "/api/contributions",
            json={"type": "new_work", "payload": '{"title": "A community addition"}'},
            headers=self.auth(self.member),
        )
        self.assertEqual(submitted.status_code, 200, submitted.text)

        # Members must not be able to read or moderate the queue.
        self.assertEqual(
            self.client.get("/api/contributions", headers=self.auth(self.member)).status_code,
            403,
        )

        queue = self.client.get("/api/contributions", headers=self.auth(self.admin))
        self.assertEqual(queue.status_code, 200, queue.text)
        self.assertEqual(len(queue.json()), 1)
        contrib_id = queue.json()[0]["id"]

        approved = self.client.post(
            f"/api/contributions/{contrib_id}/approve", headers=self.auth(self.admin)
        )
        self.assertEqual(approved.status_code, 200, approved.text)

        titles = {w["title"] for w in self.client.get("/api/works").json()}
        self.assertIn("A community addition", titles)

    def test_invalid_payload_is_rejected(self):
        bad_type = self.client.post(
            "/api/contributions",
            json={"type": "delete_everything", "payload": "{}"},
            headers=self.auth(self.member),
        )
        self.assertEqual(bad_type.status_code, 400)

        bad_json = self.client.post(
            "/api/contributions",
            json={"type": "new_work", "payload": "not json"},
            headers=self.auth(self.member),
        )
        self.assertEqual(bad_json.status_code, 400)

    def test_notifications_require_login_and_are_owner_scoped(self):
        self.assertEqual(self.client.get("/api/notifications").status_code, 401)
        mine = self.client.get("/api/notifications", headers=self.auth(self.member))
        self.assertEqual(mine.status_code, 200)
        self.assertEqual(mine.json(), [])


class NotificationEndpointTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.admin = self.register("admin@example.org")
        self.member = self.register("member@example.org")
        conn = sqlite3.connect(self.db_path)
        # user 1 = admin, user 2 = member
        conn.executemany(
            "INSERT INTO notifications (user_id, message, kind, dedupe_key, link, is_read)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            [
                (2, "Related work in your area", "neighbour", "neighbour:W3:A1", "#work=W3", 0),
                (2, "Possible collaboration", "collaboration", "collaboration:A1:A2", "#author=A2", 0),
                (2, "Already seen", "new_work", "new_work:W1:A1", "#work=W1", 1),
                (1, "Admin's own notification", "general", "general:1", None, 0),
            ],
        )
        conn.commit()
        conn.close()

    def test_listing_returns_only_own_notifications_with_metadata(self):
        resp = self.client.get("/api/notifications", headers=self.auth(self.member))
        self.assertEqual(resp.status_code, 200, resp.text)
        rows = resp.json()
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r["user_id"] == 2 for r in rows))
        self.assertEqual(
            {r["kind"] for r in rows}, {"neighbour", "collaboration", "new_work"}
        )
        self.assertIn("#work=", " ".join(r["link"] or "" for r in rows))

    def test_unread_only_filter_and_count(self):
        unread = self.client.get(
            "/api/notifications?unread_only=true", headers=self.auth(self.member)
        ).json()
        self.assertEqual(len(unread), 2)

        count = self.client.get(
            "/api/notifications/unread-count", headers=self.auth(self.member)
        )
        self.assertEqual(count.json()["unread"], 2)

    def test_cannot_mark_another_users_notification_read(self):
        # id 4 belongs to the admin; the member must not be able to touch it.
        resp = self.client.put("/api/notifications/4/read", headers=self.auth(self.member))
        self.assertEqual(resp.status_code, 404)
        still_unread = self.client.get(
            "/api/notifications/unread-count", headers=self.auth(self.admin)
        ).json()["unread"]
        self.assertEqual(still_unread, 1)

    def test_mark_all_read_is_scoped_to_the_caller(self):
        resp = self.client.put("/api/notifications/read-all", headers=self.auth(self.member))
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["updated"], 2)
        self.assertEqual(
            self.client.get(
                "/api/notifications/unread-count", headers=self.auth(self.member)
            ).json()["unread"],
            0,
        )
        self.assertEqual(
            self.client.get(
                "/api/notifications/unread-count", headers=self.auth(self.admin)
            ).json()["unread"],
            1,
            "another user's notifications must be untouched",
        )


if __name__ == "__main__":
    unittest.main()


class ReviewQueueTests(ApiTestCase):
    """The recorded duplicate backlog: /api/curation/queue and /reject.

    Distinct from /api/curation/duplicates, which recomputes pairs on each call
    and therefore cannot be worked down to zero.
    """

    def test_queue_requires_admin(self):
        self.assertEqual(self.client.get("/api/curation/queue").status_code, 401)
        admin = self.register("admin@test")
        non_admin = self.register("other@test")
        self.assertEqual(
            self.client.get("/api/curation/queue", headers=self.auth(admin)).status_code, 200
        )
        self.assertEqual(
            self.client.get("/api/curation/queue", headers=self.auth(non_admin)).status_code, 403
        )

    def test_queue_returns_both_sides_with_authors(self):
        token = self.register("admin@test")
        data = self.client.get("/api/curation/queue", headers=self.auth(token)).json()
        self.assertEqual(data["total"], 1)
        pair = data["pairs"][0]
        self.assertEqual(pair["work_id_a"], "W1")
        self.assertEqual(pair["work_id_b"], "W2")
        self.assertIn("authors_a", pair)
        self.assertIn("authors_b", pair)
        self.assertIn("doi_a", pair)

    def test_reject_removes_the_pair_from_the_queue(self):
        token = self.register("admin@test")
        resp = self.client.post(
            "/api/curation/reject",
            json={"work_id_a": "W1", "work_id_b": "W2", "note": "different editions"},
            headers=self.auth(token),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["remaining"], 0)
        after = self.client.get("/api/curation/queue", headers=self.auth(token)).json()
        self.assertEqual(after["total"], 0)

    def test_rejecting_twice_is_a_404(self):
        token = self.register("admin@test")
        body = {"work_id_a": "W1", "work_id_b": "W2"}
        self.client.post("/api/curation/reject", json=body, headers=self.auth(token))
        second = self.client.post("/api/curation/reject", json=body, headers=self.auth(token))
        self.assertEqual(second.status_code, 404)

    def test_reject_does_not_touch_the_works(self):
        token = self.register("admin@test")
        self.client.post(
            "/api/curation/reject",
            json={"work_id_a": "W1", "work_id_b": "W2"},
            headers=self.auth(token),
        )
        conn = sqlite3.connect(self.db_path)
        statuses = dict(conn.execute("SELECT id, status FROM works WHERE id IN ('W1','W2')"))
        conn.close()
        self.assertNotIn("deleted", statuses.values())

    def test_merge_closes_the_queue_entry(self):
        token = self.register("admin@test")
        resp = self.client.post(
            "/api/works/merge",
            json={"primary_id": "W1", "secondary_id": "W2"},
            headers=self.auth(token),
        )
        self.assertEqual(resp.status_code, 200)
        # The pair must not come back as pending after being merged.
        after = self.client.get("/api/curation/queue", headers=self.auth(token)).json()
        self.assertEqual(after["total"], 0)
        conn = sqlite3.connect(self.db_path)
        status = conn.execute(
            "SELECT review_status FROM duplicate_candidates WHERE work_id_a='W1'"
        ).fetchone()[0]
        conn.close()
        self.assertEqual(status, "merged")

    def test_queue_hides_pairs_whose_side_was_deleted(self):
        token = self.register("admin@test")
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE works SET status = 'deleted' WHERE id = 'W2'")
        conn.commit()
        conn.close()
        data = self.client.get("/api/curation/queue", headers=self.auth(token)).json()
        self.assertEqual(data["total"], 0)

    def test_queue_page_size_is_capped(self):
        token = self.register("admin@test")
        data = self.client.get(
            "/api/curation/queue?limit=9999", headers=self.auth(token)
        ).json()
        self.assertLessEqual(data["limit"], 200)
