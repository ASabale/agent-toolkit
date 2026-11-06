"""Smoke-run JSON stdout and unverified find marker (issue #91)."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.catalog import check_item, format_find_output  # noqa: E402
from lib.evolver import save_tool  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _tool(name: str, body: str, output: str = "json | Compact JSON result") -> str:
    return (
        "#!/usr/bin/env bash\n"
        f"# @tk-name: {name}\n"
        "# @tk-summary: Count something\n"
        "# @tk-safety: read-only\n"
        f"# @tk-output: {output}\n"
        f"# @tk-example: tk run {name}\n"
        "# @tk-verified: none\n"
        "\n"
        "set -euo pipefail\n"
        'if [[ "${TK_DRY_RUN:-0}" == "1" ]]; then\n'
        "  printf '%s\\n' '{\"dry_run\":true}'\n"
        "  exit 0\n"
        "fi\n"
        f"{body}\n"
    )


class CheckJsonStdoutTests(unittest.TestCase):
    def test_save_accepts_a_non_json_command_without_running_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.dict(os.environ, {"TK_NO_TELEMETRY": "1", "TK_STATE_DIR": ""}, clear=False):
                code, out, err = save_tool(
                    root,
                    "bad.count",
                    "Count hosts",
                    from_cmd="wc -l /etc/hosts",
                )
            self.assertEqual(code, 0, err)
            self.assertTrue(json.loads(out)["ok"])
            self.assertTrue((root / "tools" / "bad" / "count").is_file())

    def test_check_does_not_execute_non_json_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plain = root / "tools" / "bad" / "count"
            raw = root / "tools" / "bad" / "raw"
            good = root / "tools" / "bad" / "ok"
            _write(plain, _tool("bad.count", "wc -l /etc/hosts"))
            _write(raw, _tool("bad.raw", "printf '%s\\n' hello", output="raw | plain text"))
            _write(good, _tool("bad.ok", "printf '%s\\n' '{\"ok\":true}'"))
            failed = check_item(root, "bad.count")
            allowed = check_item(root, "bad.raw")
            passed = check_item(root, "bad.ok")
        self.assertTrue(failed["ok"], failed)
        self.assertFalse(any("not valid JSON" in err for err in failed["errors"]))
        self.assertTrue(allowed["ok"], allowed)
        self.assertTrue(passed["ok"], passed)

    def test_find_marks_unverified_without_a_third_line(self) -> None:
        summary = "S" * 120
        items = [
            {
                "name": "bad.count",
                "safety": "read-only",
                "summary": summary,
                "example": "tk run bad.count",
                "verified": "none",
            },
            {
                "name": "bad.ok",
                "safety": "read-only",
                "summary": "Emits JSON",
                "example": "tk run bad.ok",
                "verified": "2026-11-04",
            },
        ]
        text = format_find_output(items)
        lines = text.splitlines()
        self.assertEqual(len(lines), 4)
        self.assertIn("unverified", lines[0])
        self.assertNotIn("unverified", lines[2])
        for line in lines:
            self.assertLessEqual(len(line), 140)
