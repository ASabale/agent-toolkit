"""tk.migrate reports a move and does not copy secrets or create TK_HOME."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "tk" / "migrate"


class MigrateReportTests(unittest.TestCase):
    def test_report_names_catalog_state_and_gh_without_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secret = "ghp_migrate_secret_value"
            env = os.environ.copy()
            env["TK_ROOT_DIR"] = str(root)
            env["TK_STATE_DIR"] = str(root / "state")
            env["TK_DRY_RUN"] = "1"
            env["GH_TOKEN"] = secret
            env["TK_HOME"] = str(root / "should-not-exist")
            proc = subprocess.run(
                [str(TOOL)],
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotIn(secret, proc.stdout)
            self.assertNotIn(secret, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["dry_run"])
            self.assertFalse(payload["secrets_copied"])
            kinds = [row["kind"] for row in payload["copy"]]
            self.assertEqual(kinds, ["catalog", "catalog", "state"])
            self.assertEqual(payload["copy"][2]["path"], str(root / "state"))
            cred = payload["credentials"][0]
            self.assertEqual(cred["name"], "gh")
            self.assertFalse(cred["copied"])
            self.assertIn(cred["where"], {"already in gh", "gh not on PATH"})
            self.assertNotIn("TK_HOME", proc.stdout)
            self.assertFalse((root / "should-not-exist").exists())
            self.assertFalse((root / "state").exists())


if __name__ == "__main__":
    unittest.main()
