"""Tests for the deployment readiness check (scripts/preflight.py).

The value of preflight is that it *fails* on a misconfigured deploy, so these
tests focus on the failure paths rather than the happy one.

Usage:
    uv run python -m unittest tests.test_preflight -v
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location("preflight", ROOT / "scripts" / "preflight.py")
pf = importlib.util.module_from_spec(_spec)
# @dataclass resolves annotations through sys.modules[cls.__module__], so the
# module must be registered before exec_module runs or it raises AttributeError.
sys.modules["preflight"] = pf
_spec.loader.exec_module(pf)


class SecretKeyTests(unittest.TestCase):
    def test_missing_secret_is_an_error(self):
        with mock.patch.dict(os.environ, {"SECRET_KEY": ""}, clear=False):
            self.assertEqual(pf.check_secret_key().level, "ERROR")

    def test_short_secret_is_a_warning(self):
        with mock.patch.dict(os.environ, {"SECRET_KEY": "tooshort"}, clear=False):
            self.assertEqual(pf.check_secret_key().level, "WARN")

    def test_strong_secret_passes(self):
        with mock.patch.dict(os.environ, {"SECRET_KEY": "a" * 64}, clear=False):
            self.assertEqual(pf.check_secret_key().level, "OK")


class AllowedOriginsTests(unittest.TestCase):
    def test_wildcard_origin_is_an_error(self):
        # allow_credentials=True + "*" would expose authenticated endpoints to
        # any site, which is the whole point of catching it here.
        with mock.patch.dict(os.environ, {"ALLOWED_ORIGINS": "*"}, clear=False):
            check = pf.check_allowed_origins()
        self.assertEqual(check.level, "ERROR")

    def test_unset_origins_is_only_a_warning(self):
        with mock.patch.dict(os.environ, {"ALLOWED_ORIGINS": ""}, clear=False):
            self.assertEqual(pf.check_allowed_origins().level, "WARN")

    def test_explicit_origin_passes(self):
        with mock.patch.dict(
            os.environ, {"ALLOWED_ORIGINS": "https://example.org"}, clear=False
        ):
            self.assertEqual(pf.check_allowed_origins().level, "OK")


class ExportFreshnessTests(unittest.TestCase):
    """The stale-export check is the one that prevents shipping a graph that
    disagrees with the database, so it gets its own coverage."""

    def test_export_older_than_database_is_an_error(self):
        # Path objects reject attribute patching, so point the module at real
        # temp files with controlled mtimes instead.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            export = tmp_path / "data.json"
            database = tmp_path / "syriac.db"
            export.write_text(
                json.dumps({"works": [], "authors": [], "clusters": [], "meta": {}}),
                encoding="utf-8",
            )
            database.write_bytes(b"\x00")
            os.utime(export, (1_000_000, 1_000_000))
            os.utime(database, (2_000_000, 2_000_000))

            with mock.patch.object(pf, "JSON_PATH", export), mock.patch.object(
                pf, "DB_PATH", database
            ):
                checks = pf.check_export()

        messages = [c.message for c in checks if c.level == "ERROR"]
        self.assertTrue(
            any("older than the database" in m for m in messages),
            f"expected a staleness error, got {[c.message for c in checks]}",
        )

    def test_missing_export_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(pf, "JSON_PATH", Path(tmp) / "absent.json"):
                checks = pf.check_export()
        self.assertEqual(checks[0].level, "ERROR")

    def test_current_export_is_reported_ok(self):
        checks = pf.check_export()
        self.assertTrue(
            any(c.level == "OK" and "newer than the database" in c.message for c in checks)
        )


class RealRepositoryTests(unittest.TestCase):
    """Guards against the repo drifting into an undeployable state."""

    def test_env_is_gitignored(self):
        checks = pf.check_files(static_only=True)
        env_check = next(c for c in checks if ".env is gitignored" in c.message or "not gitignored" in c.message)
        self.assertEqual(env_check.level, "OK")

    def test_static_target_needs_no_secrets(self):
        with mock.patch.dict(os.environ, {"SECRET_KEY": ""}, clear=False):
            checks = pf.check_export() + pf.check_files(static_only=True)
        self.assertEqual([c for c in checks if c.level == "ERROR"], [])

    def test_deployment_docs_exist(self):
        self.assertTrue((ROOT / "DEPLOYMENT.md").exists())
        self.assertTrue((ROOT / ".env.example").exists())


if __name__ == "__main__":
    unittest.main()
