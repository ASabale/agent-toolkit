"""Single-tool tk run must inherit stdin, not pre-read it (issue #11)."""

from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TK = ROOT / "tk"


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["TK_NO_TELEMETRY"] = "1"
    return env


class StdinPassthroughTests(unittest.TestCase):
    def test_open_silent_stdin_pipe_does_not_hang_non_stdin_tool(self) -> None:
        proc = subprocess.Popen(
            [str(TK), "run", "env.check", "--bins", "git", "--vars", "none"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(ROOT),
            env=_env(),
        )
        try:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
                self.fail("tk run hung while an open stdin PIPE was left unread")
            stdout = proc.stdout.read() if proc.stdout is not None else ""
            stderr = proc.stderr.read() if proc.stderr is not None else ""
        finally:
            if proc.stdin is not None:
                proc.stdin.close()
            if proc.stdout is not None:
                proc.stdout.close()
            if proc.stderr is not None:
                proc.stderr.close()
        self.assertEqual(proc.returncode, 0, stderr)
        payload = json.loads(stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["binaries"][0]["name"], "git")

    def test_piped_json_reaches_json_pick(self) -> None:
        completed = subprocess.run(
            [str(TK), "run", "json.pick", "--keys", "a"],
            input='{"a":1,"b":2}\n',
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            env=_env(),
            timeout=5,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), {"a": 1})


if __name__ == "__main__":
    unittest.main()
