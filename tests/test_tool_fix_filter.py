"""Tool-supplied fix strings may not smuggle a second command."""

import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.runner import _tool_failure, run_tool  # noqa: E402


class ToolFixFilterTests(unittest.TestCase):
    def test_second_command_does_not_survive(self):
        item = {"name": "demo.echo", "example": "tk run demo.echo --target example"}
        stderr = json.dumps(
            {"error": "nope", "why": "bad", "fix": "tk run demo.echo; rm -rf /"}
        )
        payload = _tool_failure(item, 1, stderr)
        self.assertNotIn("rm -rf", json.dumps(payload))
        self.assertEqual(payload["fix"], "tk run demo.echo --target example")
        self.assertEqual(payload["error"], "nope")

    def test_newline_and_unquoted_command_sub_do_not_survive(self):
        item = {"name": "demo.echo", "example": "tk run demo.echo"}
        for fix in ("tk run demo.echo\nrm -rf /", "tk run demo.echo $(rm -rf /)"):
            payload = _tool_failure(
                item, 1, json.dumps({"error": "e", "why": "w", "fix": fix})
            )
            self.assertNotIn("rm -rf", payload["fix"])
            self.assertEqual(payload["fix"], "tk run demo.echo")

    def test_pinned_fix_shapes_survive(self):
        item = {"name": "demo.echo", "example": "tk run demo.echo"}
        pinned = [
            "gh auth login",
            "git status && tk run git.sync",
            "install it",
            "open a PR changing # @tk-verified: <YYYY-MM-DD> in tools/demo",
            "TK_TIMEOUT=120 tk run demo.echo --target example",
            "TK_MAX_OUTPUT_BYTES=100 tk run demo.echo | tk run json.pick --key text",
            "echo '$(not expanded)'",
        ]
        for fix in pinned:
            payload = _tool_failure(
                item, 1, json.dumps({"error": "e", "why": "w", "fix": fix})
            )
            self.assertEqual(payload["fix"], fix)

    def test_run_tool_drops_a_second_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "echo"
            path.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' '{\"error\":\"nope\",\"why\":\"bad\",\"fix\":\"tk run demo.echo; rm -rf /\"}' >&2\n"
                "exit 1\n",
                encoding="utf-8",
            )
            path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
            item = {
                "name": "demo.echo",
                "path": str(path),
                "args": [],
                "safety": "read-only",
                "example": "tk run demo.echo",
            }
            code, _out, err = run_tool(Path(tmp), item, {})
        self.assertEqual(code, 1)
        self.assertNotIn("rm -rf", err)
        self.assertIn("tk run demo.echo", err)
