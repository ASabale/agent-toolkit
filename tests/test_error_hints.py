"""Each error hint is a command that runs, or gh auth login (issue #95)."""

from __future__ import annotations

import json
import os
import shlex
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(args: list[str], env: dict | None = None, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged["TK_NO_TELEMETRY"] = "1"
    merged["PATH"] = str(ROOT) + os.pathsep + merged.get("PATH", "")
    if env:
        merged.update(env)
    return subprocess.run(
        [sys.executable, str(ROOT / "tk"), *args],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env=merged,
        check=False,
    )


def _json_line(text: str) -> dict:
    lines = [line for line in text.splitlines() if line.strip()]
    return json.loads(lines[-1])


class ErrorHintTests(unittest.TestCase):
    def test_no_match_suggests_closest_namespace_and_that_command_runs(self) -> None:
        missed = _run(["find", "gitt"])
        self.assertEqual(missed.returncode, 0, missed.stderr)
        payload = _json_line(missed.stderr)
        self.assertEqual(payload["error"], "no_match")
        self.assertEqual(payload["fix"], "tk find --namespace git")
        self.assertNotIn("<", payload["fix"])
        healed = _run(shlex.split(payload["fix"])[1:])
        self.assertEqual(healed.returncode, 0, healed.stderr)
        self.assertIn("git.", healed.stdout)

    def test_check_failed_names_the_item_and_that_command_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            draft = Path(tmp) / "broken.py"
            draft.write_text(
                "#!/usr/bin/env python3\n"
                "# @tk-name: lab.broken\n"
                "# @tk-summary: Broken on purpose\n"
                "# @tk-safety: read-only\n"
                "# @tk-output: json | {ok}\n"
                "# @tk-example: tk run lab.broken\n"
                "# @tk-verified: none\n"
                "def (\n",
                encoding="utf-8",
            )
            saved = _run(
                [
                    "save",
                    "lab.broken",
                    "--summary",
                    "Broken on purpose",
                    "--safety",
                    "read-only",
                    "--file",
                    str(draft),
                ]
            )
        self.assertEqual(saved.returncode, 1, saved.stderr)
        payload = _json_line(saved.stderr)
        self.assertEqual(payload["error"], "check_failed")
        self.assertEqual(payload["fix"], "tk check lab.broken --json")
        healed = _run(shlex.split(payload["fix"])[1:])
        self.assertNotEqual(healed.returncode, 2, healed.stderr)
        body = json.loads(healed.stdout)
        self.assertIn("lab.broken", json.dumps(body))

    def test_gh_failed_when_logged_out_is_gh_auth_login(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "gh"
            fake.write_text(
                "#!/bin/sh\n"
                "echo 'You are not logged into any GitHub hosts' >&2\n"
                "exit 1\n",
                encoding="utf-8",
            )
            fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
            failed = _run(
                ["run", "gh.issue-view", "--repo", "cli/cli", "--number", "1"],
                env={"PATH": str(tmp) + os.pathsep + os.environ.get("PATH", "")},
            )
        self.assertEqual(failed.returncode, 1, failed.stderr)
        payload = _json_line(failed.stderr)
        self.assertEqual(payload["error"], "gh_failed")
        self.assertEqual(payload["fix"], "gh auth login")

    def test_unknown_flag_keeps_the_value_on_the_closest_flag_and_that_command_runs(self) -> None:
        failed = _run(
            ["run", "json.pick", "--key", "branch"],
            stdin='{"branch":"main","extra":1}\n',
        )
        self.assertEqual(failed.returncode, 1, failed.stderr)
        payload = _json_line(failed.stderr)
        self.assertEqual(payload["error"], "unknown_flag")
        self.assertIn("--key (did you mean --keys?)", payload["why"])
        self.assertEqual(payload["fix"], "tk run json.pick --keys branch")
        self.assertNotIn("--key ", payload["fix"])
        healed = _run(shlex.split(payload["fix"])[1:], stdin='{"branch":"main","extra":1}\n')
        self.assertEqual(healed.returncode, 0, healed.stderr)
        self.assertEqual(json.loads(healed.stdout), {"branch": "main"})

    def test_output_too_large_narrows_and_that_command_runs(self) -> None:
        failed = _run(["run", "env.check"], env={"TK_MAX_OUTPUT_BYTES": "16"})
        self.assertEqual(failed.returncode, 1, failed.stderr)
        payload = _json_line(failed.stderr)
        self.assertEqual(payload["error"], "output_too_large")
        fix = payload["fix"]
        self.assertLess(len(fix.encode()), 2000, fix)
        self.assertTrue(
            "--limit" in fix or "--keys" in fix or fix.rstrip().endswith("| head"),
            fix,
        )
        merged = os.environ.copy()
        merged["TK_NO_TELEMETRY"] = "1"
        merged["TK_MAX_OUTPUT_BYTES"] = "16"
        merged["PATH"] = str(ROOT) + os.pathsep + merged.get("PATH", "")
        healed = subprocess.run(
            fix,
            shell=True,
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            env=merged,
            check=False,
        )
        self.assertEqual(healed.returncode, 0, healed.stderr + healed.stdout)
        self.assertTrue(healed.stdout.strip())

    def test_help_exits_zero(self) -> None:
        for args in (["--help"], ["-h"], ["help"], []):
            with self.subTest(args=args):
                proc = _run(args)
                self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_log_tail_fix_echoes_repo_and_pr_and_passes_validation(self) -> None:
        failed = _run(
            [
                "run",
                "gh.pr-failure-digest",
                "--repo",
                "cli/cli",
                "--pr",
                "1",
                "--log-tail",
                "-1",
            ]
        )
        self.assertEqual(failed.returncode, 2, failed.stderr)
        payload = _json_line(failed.stderr)
        self.assertEqual(payload["error"], "invalid_flag")
        fix = payload["fix"]
        self.assertEqual(
            fix,
            "tk run gh.pr-failure-digest --repo cli/cli --pr 1 --log-tail 30",
        )
        self.assertNotIn("<", fix)
        healed = _run(shlex.split(fix)[1:])
        self.assertNotEqual(healed.returncode, 2, healed.stderr)
        if healed.returncode != 0:
            rejected = _json_line(healed.stderr)
            self.assertNotIn(
                rejected["error"],
                {"invalid_flag", "unknown_flag", "missing_required", "invalid_type"},
            )


if __name__ == "__main__":
    unittest.main()
