"""Seams for sys.proc-info and env.check."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRET = "super-secret-value-123"


def _run(script: Path, env: dict) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    for key in list(merged):
        if key.startswith("TK_ARG_") or key == "TK_DRY_RUN":
            merged.pop(key, None)
    merged.update(env)
    merged.setdefault("TK_DRY_RUN", "0")
    return subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        env=merged,
    )


class ProcInfoTests(unittest.TestCase):
    def test_matches_current_process_pid(self) -> None:
        pid = str(os.getpid())
        proc = _run(
            ROOT / "tools/sys/proc-info",
            {"TK_ARG_QUERY": pid, "TK_ARG_LIMIT": "15"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["query"], pid)
        self.assertFalse(payload["truncated"])
        self.assertGreaterEqual(payload["count"], 1)
        matched = [row for row in payload["processes"] if row["pid"] == int(pid)]
        self.assertEqual(len(matched), 1)
        row = matched[0]
        self.assertIsInstance(row["ppid"], int)
        self.assertIsInstance(row["cpu"], float)
        self.assertIsInstance(row["rss_kb"], int)
        self.assertIsInstance(row["command"], str)
        self.assertTrue(row["command"])

    def test_dry_run_skips_ps(self) -> None:
        proc = _run(
            ROOT / "tools/sys/proc-info",
            {"TK_ARG_QUERY": "example", "TK_ARG_LIMIT": "3", "TK_DRY_RUN": "1"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            json.loads(proc.stdout),
            {"dry_run": True, "query": "example", "limit": 3},
        )


class EnvCheckTests(unittest.TestCase):
    def test_reports_found_and_missing_bins_and_hides_secret_value(self) -> None:
        proc = _run(
            ROOT / "tools/env/check",
            {
                "TK_ARG_BINS": "python3,tk-missing-bin-zz",
                "TK_ARG_VARS": "SECRET_TOKEN,TK_MISSING_VAR_ZZ",
                "SECRET_TOKEN": SECRET,
            },
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn(SECRET, proc.stdout)
        self.assertNotIn(SECRET, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["ok"])
        by_bin = {item["name"]: item for item in payload["binaries"]}
        self.assertTrue(by_bin["python3"]["found"])
        self.assertIsInstance(by_bin["python3"]["path"], str)
        self.assertFalse(by_bin["tk-missing-bin-zz"]["found"])
        self.assertIsNone(by_bin["tk-missing-bin-zz"]["path"])
        self.assertEqual(payload["missing_bins"], ["tk-missing-bin-zz"])
        by_var = {item["name"]: item for item in payload["variables"]}
        self.assertEqual(by_var["SECRET_TOKEN"], {"name": "SECRET_TOKEN", "set": True, "length": 22})
        self.assertEqual(
            by_var["TK_MISSING_VAR_ZZ"],
            {"name": "TK_MISSING_VAR_ZZ", "set": False, "length": 0},
        )
        self.assertEqual(payload["missing_vars"], ["TK_MISSING_VAR_ZZ"])
        self.assertEqual(len(SECRET), 22)

    def test_dry_run(self) -> None:
        proc = _run(
            ROOT / "tools/env/check",
            {"TK_ARG_BINS": "git", "TK_ARG_VARS": "HOME", "TK_DRY_RUN": "1"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            json.loads(proc.stdout),
            {"dry_run": True, "bins": "git", "vars": "HOME"},
        )


if __name__ == "__main__":
    unittest.main()
