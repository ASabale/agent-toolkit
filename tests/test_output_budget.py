"""One output cap: TK_MAX_OUTPUT_BYTES, default 65536."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from lib.runner import run_tool

ROOT = Path(__file__).resolve().parents[1]


class OutputBudgetTests(unittest.TestCase):
    def test_runner_has_one_output_cap(self):
        runner = (ROOT / "lib" / "runner.py").read_text(encoding="utf-8")
        cli = (ROOT / "tk").read_text(encoding="utf-8")
        self.assertEqual(runner.count('os.environ.get("TK_MAX_OUTPUT_BYTES"'), 1)
        self.assertIn('_positive_int(os.environ.get("TK_MAX_OUTPUT_BYTES", ""), 65536)', runner)
        self.assertNotIn("TK_MAX_OUTPUT_BYTES", cli)
        self.assertNotIn("--max-output", cli)

    def test_over_cap_is_the_existing_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "wide"
            script.write_text(
                "#!/bin/sh\nprintf '%s\\n' '{\"ok\":true,\"pad\":\"xxxxxxxx\"}'\n",
                encoding="utf-8",
            )
            script.chmod(script.stat().st_mode | stat.S_IXUSR)
            previous = os.environ.get("TK_MAX_OUTPUT_BYTES")
            os.environ["TK_MAX_OUTPUT_BYTES"] = "8"
            try:
                code, out, err = run_tool(
                    root,
                    {
                        "name": "demo.wide",
                        "path": str(script),
                        "safety": "read-only",
                        "args": [],
                        "example": "tk run demo.wide",
                        "kind": "tool",
                    },
                    {},
                )
            finally:
                if previous is None:
                    os.environ.pop("TK_MAX_OUTPUT_BYTES", None)
                else:
                    os.environ["TK_MAX_OUTPUT_BYTES"] = previous
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(json.loads(err)["error"], "output_too_large")


if __name__ == "__main__":
    unittest.main()
