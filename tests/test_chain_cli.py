"""CLI tests for the VISION `tk chain <name> '<step>'` form."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ChainCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "toolkit"
        shutil.copytree(
            ROOT,
            self.root,
            ignore=shutil.ignore_patterns(
                "__pycache__",
                "*.pyc",
                ".git",
                "state",
                ".code-review-graph",
            ),
        )
        self.tk = self.root / "tk"
        self.tk.chmod(self.tk.stat().st_mode | 0o755)
        # The acceptance step names a tool this tree does not ship. The fixture
        # lives only in the temp copy so `tk check` can see it; source chains/ stay untouched.
        stub = self.root / "tools" / "sys" / "env-digest"
        stub.write_text(
            "#!/usr/bin/env bash\n"
            "# @tk-name: sys.env-digest\n"
            "# @tk-summary: Digest environment variable names from the current process\n"
            "# @tk-safety: read-only\n"
            "# @tk-output: json | {a}\n"
            "# @tk-example: tk run sys.env-digest\n"
            "# @tk-verified: none\n"
            "printf '{\"names\":[]}\n'\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)
        self.env = os.environ.copy()
        self.env["TK_NO_TELEMETRY"] = "1"
        self.env["TK_STATE_DIR"] = ""

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.tk), *args],
            capture_output=True,
            text=True,
            cwd=self.root,
            env=self.env,
        )

    def _chain(self, name: str) -> dict:
        return json.loads((self.root / "chains" / f"{name}.json").read_text(encoding="utf-8"))

    def test_vision_form_matches_chain_save(self) -> None:
        vision = self._run("chain", "demo.x", "sys.env-digest", "json.pick --keys a")
        self.assertEqual(vision.returncode, 0, vision.stderr)
        saved = self._run(
            "chain",
            "save",
            "demo.y",
            "--summary",
            "sys.env-digest → json.pick --keys a",
            "--steps",
            '[{"tool":"sys.env-digest"},{"tool":"json.pick","args":{"keys":"a"}}]',
        )
        self.assertEqual(saved.returncode, 0, saved.stderr)
        left = self._chain("demo.x")
        right = self._chain("demo.y")
        self.assertEqual(left["steps"], right["steps"])
        self.assertEqual(left["kind"], right["kind"])
        self.assertEqual(left["safety"], right["safety"])
        self.assertEqual(left["verified"], right["verified"])
        self.assertEqual(left["summary"], right["summary"])
        self.assertFalse((ROOT / "chains" / "demo.x.json").exists())
        self.assertFalse((ROOT / "chains" / "demo.y.json").exists())

    def test_equals_flag_and_explicit_summary(self) -> None:
        proc = self._run(
            "chain",
            "demo.eq",
            "--summary",
            "picked",
            "--safety",
            "read-only",
            "json.pick --keys=a",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        doc = self._chain("demo.eq")
        self.assertEqual(doc["summary"], "picked")
        self.assertEqual(doc["safety"], "read-only")
        self.assertEqual(doc["steps"], [{"tool": "json.pick", "args": {"keys": "a"}}])

    def test_name_with_only_flags_still_runs(self) -> None:
        before = sorted(p.name for p in (self.root / "chains").glob("*.json"))
        proc = self._run("chain", "git.repo-audit", "--dry-run")
        after = sorted(p.name for p in (self.root / "chains").glob("*.json"))
        self.assertEqual(before, after)
        self.assertNotIn("chain_saved", proc.stdout)
        # A run, not a save: dry-run still needs the required --repo flag.
        payload = json.loads(proc.stderr)
        self.assertNotEqual(payload.get("error"), "unknown_flag")
        self.assertNotEqual(payload.get("error"), "invalid_steps")

    def test_bare_flag_is_invalid_steps_with_quoted_fix(self) -> None:
        proc = self._run("chain", "demo.bare", "json.pick --keys")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        payload = json.loads(proc.stderr)
        self.assertEqual(payload["error"], "invalid_steps")
        self.assertIn("'json.pick --keys <value>'", payload["fix"])
        self.assertFalse((self.root / "chains" / "demo.bare.json").exists())

    def test_unknown_flag_points_at_chain_save(self) -> None:
        proc = self._run("chain", "demo.bad", "sys.env-digest", "--nope", "1")
        self.assertEqual(proc.returncode, 2)
        payload = json.loads(proc.stderr)
        self.assertEqual(payload["error"], "unknown_flag")
        self.assertEqual(
            payload["fix"],
            'tk chain save demo.bad --summary "<text>" --steps \'<json>\'',
        )


    def test_flag_value_still_runs_chain(self) -> None:
        before = sorted(p.name for p in (self.root / "chains").glob("*.json"))
        proc = self._run("chain", "git.repo-audit", "--repo", ".", "--dry-run")
        after = sorted(p.name for p in (self.root / "chains").glob("*.json"))
        self.assertEqual(before, after)
        self.assertNotIn("chain_saved", proc.stdout)
        if proc.stderr.strip():
            payload = json.loads(proc.stderr)
            self.assertNotEqual(payload.get("error"), "unknown_flag")
            self.assertNotEqual(payload.get("error"), "invalid_steps")
        repo = self._run("chain", "git.repo-audit", "--repo", ".")
        self.assertEqual(before, sorted(p.name for p in (self.root / "chains").glob("*.json")))
        self.assertNotIn("chain_saved", repo.stdout)
        if repo.stderr.strip():
            payload = json.loads(repo.stderr)
            self.assertNotEqual(payload.get("error"), "unknown_flag")
            self.assertNotEqual(payload.get("error"), "invalid_steps")

    def test_force_does_not_swallow_step(self) -> None:
        proc = self._run("chain", "demo.force", "--force", "sys.env-digest")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self._chain("demo.force")["steps"], [{"tool": "sys.env-digest"}])
        self.assertFalse((ROOT / "chains" / "demo.force.json").exists())

    def test_no_args_unchanged(self) -> None:
        proc = self._run("chain")
        self.assertEqual(proc.returncode, 2)
        payload = json.loads(proc.stderr)
        self.assertEqual(payload["error"], "usage")
        self.assertIn("tk chain save", payload["fix"])
