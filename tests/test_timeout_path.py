"""One tool timeout path: TK_TIMEOUT, default 60s, exit 1."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from lib.runner import run_tool

ROOT = Path(__file__).resolve().parents[1]


class TimeoutPathTests(unittest.TestCase):
    def test_runner_has_one_tk_timeout_read(self):
        runner = (ROOT / "lib" / "runner.py").read_text(encoding="utf-8")
        cli = (ROOT / "tk").read_text(encoding="utf-8")
        self.assertEqual(runner.count('os.environ.get("TK_TIMEOUT"'), 1)
        self.assertIn('_positive_float(os.environ.get("TK_TIMEOUT", ""), 60.0)', runner)
        self.assertNotIn("--timeout", cli)
        start = runner.index('"error": "tool_timeout"')
        window = runner[start:start + 240]
        self.assertIn("1,", runner[start - 80:start])
        self.assertNotIn("124", window)

    def test_timeout_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "slow"
            script.write_text(
                "#!/bin/sh\nsleep 30\nprintf '%s\\n' '{\"ok\":true}'\n",
                encoding="utf-8",
            )
            script.chmod(script.stat().st_mode | stat.S_IXUSR)
            previous = os.environ.get("TK_TIMEOUT")
            os.environ["TK_TIMEOUT"] = "1"
            try:
                code, out, err = run_tool(
                    root,
                    {
                        "name": "demo.slow",
                        "path": str(script),
                        "safety": "read-only",
                        "args": [],
                        "example": "tk run demo.slow",
                        "kind": "tool",
                    },
                    {},
                )
            finally:
                if previous is None:
                    os.environ.pop("TK_TIMEOUT", None)
                else:
                    os.environ["TK_TIMEOUT"] = previous
        self.assertEqual(code, 1)
        self.assertNotEqual(code, 124)
        self.assertEqual(out, "")
        self.assertEqual(json.loads(err)["error"], "tool_timeout")


if __name__ == "__main__":
    unittest.main()
