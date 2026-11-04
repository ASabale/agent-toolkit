"""md.section: --heading outline extracts an Outline heading; --outline is the tree."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECTION = ROOT / "tools/md/section"
TK = ROOT / "tk"

DOC = """\
# Title

intro

## Outline

section body

## Later

more
"""


def _script(env: dict) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    for key in list(merged):
        if key.startswith("TK_ARG_") or key == "TK_DRY_RUN":
            merged.pop(key, None)
    merged.update(env)
    merged.setdefault("TK_DRY_RUN", "0")
    return subprocess.run(
        [sys.executable, str(SECTION)],
        capture_output=True,
        text=True,
        env=merged,
    )


def _tk(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["TK_NO_TELEMETRY"] = "1"
    for key in list(env):
        if key.startswith("TK_ARG_") or key == "TK_DRY_RUN":
            env.pop(key, None)
    return subprocess.run(
        [str(TK), *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
    )


class HeadingOutlineTests(unittest.TestCase):
    def test_heading_outline_returns_outline_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.md"
            path.write_text(DOC, encoding="utf-8")
            result = _script(
                {"TK_ARG_PATH": str(path), "TK_ARG_HEADING": "outline", "TK_ARG_MAX_LINES": "60"},
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["heading"], "Outline")
        self.assertEqual(payload["level"], 2)
        self.assertIn("section body", payload["content"])
        self.assertNotIn("more", payload["content"])
        self.assertNotIn("mode", payload)
        self.assertEqual(
            set(payload),
            {"path", "heading", "level", "start_line", "end_line", "truncated", "content"},
        )

    def test_cli_heading_outline_returns_outline_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.md"
            path.write_text(DOC, encoding="utf-8")
            result = _tk("run", "md.section", "--path", str(path), "--heading", "outline")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["heading"], "Outline")
        self.assertIn("section body", payload["content"])
        self.assertNotIn("mode", payload)

    def test_omitted_heading_stays_outline_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.md"
            path.write_text(DOC, encoding="utf-8")
            via_script = _script({"TK_ARG_PATH": str(path), "TK_ARG_MAX_LINES": "60"})
            via_cli = _tk("run", "md.section", "--path", str(path))
        for result in (via_script, via_cli):
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["mode"], "outline")
            self.assertEqual(
                [item["title"] for item in payload["headings"]],
                ["Title", "Outline", "Later"],
            )
            self.assertEqual(set(payload), {"path", "mode", "count", "truncated", "headings"})

    def test_outline_flag_returns_tree_when_outline_heading_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.md"
            path.write_text(DOC, encoding="utf-8")
            via_script = _script(
                {
                    "TK_ARG_PATH": str(path),
                    "TK_ARG_OUTLINE": "true",
                    "TK_ARG_HEADING": "outline",
                    "TK_ARG_MAX_LINES": "60",
                },
            )
            via_cli = _tk("run", "md.section", "--path", str(path), "--outline")
        for result in (via_script, via_cli):
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["mode"], "outline")
            self.assertEqual(payload["count"], 3)
            self.assertEqual(payload["truncated"], 0)
            self.assertEqual(
                [item["title"] for item in payload["headings"]],
                ["Title", "Outline", "Later"],
            )

    def test_heading_outline_falls_back_to_tree_when_no_heading_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.md"
            path.write_text("# Title\n\n## Next\n", encoding="utf-8")
            result = _script(
                {"TK_ARG_PATH": str(path), "TK_ARG_HEADING": "outline", "TK_ARG_MAX_LINES": "60"},
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["mode"], "outline")
        self.assertEqual([item["title"] for item in payload["headings"]], ["Title", "Next"])

    def test_info_describes_each_flag_with_one_meaning(self) -> None:
        result = _tk("info", "md.section")
        self.assertEqual(result.returncode, 0, result.stderr)
        text = result.stdout
        self.assertIn("--heading | optional | string | Heading substring to extract", text)
        self.assertIn("--outline | optional | bool |", text)
        self.assertIn("heading tree", text.casefold())
        heading_line = next(line for line in text.splitlines() if line.strip().startswith("--heading"))
        outline_line = next(line for line in text.splitlines() if line.strip().startswith("--outline"))
        self.assertNotIn("outline", heading_line.casefold())
        self.assertNotIn("substring", outline_line.casefold())
        self.assertNotIn("or outline", text.casefold())


if __name__ == "__main__":
    unittest.main()
