"""Schema fixtures live next to tests, not in tools/."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from lib.catalog import check_item

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


class SchemaFixtureTests(unittest.TestCase):
    def test_fixtures_are_not_in_tools(self):
        for path in (FIXTURES / "schema_ok", FIXTURES / "schema_missing"):
            self.assertTrue(path.is_file(), path)
            self.assertNotIn("/tools/", f"/{path.relative_to(ROOT).as_posix()}/")
            self.assertTrue(os.access(path, os.X_OK), path)

    def test_schema_ok_fixture_passes(self):
        result = check_item(ROOT, FIXTURES / "schema_ok")
        self.assertTrue(result["ok"], result)
        self.assertNotIn("sandbox", " ".join(result["errors"]).lower())

    def test_schema_missing_fixture_names_the_key(self):
        result = check_item(ROOT, FIXTURES / "schema_missing")
        blob = " ".join(result["errors"])
        self.assertIn("count", blob)
        self.assertIn("fix:", blob)
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
