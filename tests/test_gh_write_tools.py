"""Seams for gh.comment and gh.label: dry-run plan, confirmed argv, auth failure."""

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_FAKE_GH = """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

log = Path(os.environ["GH_LOG"])
previous = []
if log.is_file():
    previous = json.loads(log.read_text(encoding="utf-8") or "[]")
previous.append(sys.argv[1:])
log.write_text(json.dumps(previous), encoding="utf-8")
mode = os.environ.get("GH_MODE", "json")
if mode == "auth":
    sys.stderr.write("HTTP 401: bad credentials\\n")
    raise SystemExit(1)
if mode == "plain" or "comment" not in sys.argv:
    raise SystemExit(0)
sys.stdout.write(json.dumps({"url": "https://github.com/acme/widgets/issues/4#issuecomment-9", "body": "secret"}))
"""


class GhWriteToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        fake = root / "gh"
        fake.write_text(_FAKE_GH, encoding="utf-8")
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        self.log = root / "gh.log"
        self.env = os.environ.copy()
        self.env["PATH"] = str(root) + os.pathsep + self.env.get("PATH", "")
        self.env["GH_LOG"] = str(self.log)
        self.env["TK_NO_TELEMETRY"] = "1"
        self.env["TK_STATE_DIR"] = str(root / "state")
        for key in list(self.env):
            if key.startswith("TK_ARG_") or key == "TK_DRY_RUN":
                self.env.pop(key, None)

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(ROOT / "tk"), *args],
            capture_output=True,
            text=True,
            cwd=ROOT,
            env=self.env,
        )

    def _calls(self) -> list:
        if not self.log.is_file():
            return []
        return json.loads(self.log.read_text(encoding="utf-8"))

    def test_comment_dry_run_does_not_execute_gh(self) -> None:
        proc = self._run(
            "run",
            "gh.comment",
            "--kind",
            "issue",
            "--repo",
            "acme/widgets",
            "--number",
            "4",
            "--body",
            "secret body",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["dry_run"])
        self.assertEqual(
            payload["plan"],
            ["gh", "issue", "comment", "4", "--repo", "acme/widgets", "--body", "secret body"],
        )
        self.assertTrue(payload["apply"].endswith("--yes"))
        self.assertEqual(self._calls(), [])
        self.assertNotIn("commented", payload)

    def test_comment_yes_records_argv_and_url_without_body(self) -> None:
        proc = self._run(
            "run",
            "gh.comment",
            "--kind",
            "pr",
            "--repo",
            "acme/widgets",
            "--number",
            "4",
            "--body",
            "secret body",
            "--yes",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            self._calls(),
            [["pr", "comment", "4", "--repo", "acme/widgets", "--body", "secret body"]],
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(
            payload,
            {
                "repo": "acme/widgets",
                "number": 4,
                "kind": "pr",
                "url": "https://github.com/acme/widgets/issues/4#issuecomment-9",
            },
        )

    def test_comment_without_json_reports_commented(self) -> None:
        self.env["GH_MODE"] = "plain"
        proc = self._run(
            "run",
            "gh.comment",
            "--kind",
            "issue",
            "--repo",
            "acme/widgets",
            "--number",
            "4",
            "--body",
            "secret body",
            "--yes",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            json.loads(proc.stdout),
            {"repo": "acme/widgets", "number": 4, "kind": "issue", "commented": True},
        )
        self.assertNotIn("secret body", proc.stdout)

    def test_comment_auth_failure(self) -> None:
        self.env["GH_MODE"] = "auth"
        proc = self._run(
            "run",
            "gh.comment",
            "--kind",
            "issue",
            "--repo",
            "acme/widgets",
            "--number",
            "4",
            "--body",
            "secret body",
            "--yes",
        )
        self.assertNotEqual(proc.returncode, 0)
        payload = json.loads(proc.stderr)
        self.assertEqual(payload["error"], "gh_failed")
        self.assertEqual(payload["fix"], "gh auth login")
        self.assertNotIn("secret body", proc.stderr)

    def test_label_dry_run_plan(self) -> None:
        proc = self._run(
            "run",
            "gh.label",
            "--kind",
            "issue",
            "--repo",
            "acme/widgets",
            "--number",
            "9",
            "--add",
            "bug",
            "--remove",
            "triage",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["dry_run"])
        self.assertEqual(
            payload["plan"],
            [
                "gh",
                "issue",
                "edit",
                "9",
                "--repo",
                "acme/widgets",
                "--add-label",
                "bug",
                "--remove-label",
                "triage",
            ],
        )
        self.assertTrue(payload["apply"].endswith("--yes"))
        self.assertEqual(self._calls(), [])

    def test_label_yes_records_argv(self) -> None:
        proc = self._run(
            "run",
            "gh.label",
            "--kind",
            "pr",
            "--repo",
            "acme/widgets",
            "--number",
            "9",
            "--add",
            "bug",
            "--yes",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            self._calls(),
            [["pr", "edit", "9", "--repo", "acme/widgets", "--add-label", "bug"]],
        )
        self.assertEqual(
            json.loads(proc.stdout),
            {"repo": "acme/widgets", "number": 9, "kind": "pr", "added": "bug", "removed": None},
        )

    def test_label_requires_add_or_remove(self) -> None:
        proc = self._run(
            "run",
            "gh.label",
            "--kind",
            "issue",
            "--repo",
            "acme/widgets",
            "--number",
            "9",
            "--yes",
        )
        self.assertEqual(proc.returncode, 2, proc.stderr)
        payload = json.loads(proc.stderr)
        self.assertEqual(payload["error"], "missing_flag")
        self.assertIn("acme/widgets", payload["fix"])
        self.assertIn("9", payload["fix"])
        self.assertEqual(self._calls(), [])

    def test_label_auth_failure(self) -> None:
        self.env["GH_MODE"] = "auth"
        proc = self._run(
            "run",
            "gh.label",
            "--kind",
            "issue",
            "--repo",
            "acme/widgets",
            "--number",
            "9",
            "--remove",
            "triage",
            "--yes",
        )
        self.assertNotEqual(proc.returncode, 0)
        payload = json.loads(proc.stderr)
        self.assertEqual(payload["error"], "gh_failed")
        self.assertEqual(payload["fix"], "gh auth login")


if __name__ == "__main__":
    unittest.main()
