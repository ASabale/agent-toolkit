"""Run README fences only when they are already valid tk commands."""

from __future__ import annotations

import os
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
FENCE = re.compile(r"```([^\n`]*)\n(.*?)```", re.DOTALL)


def _fences(text: str) -> list[tuple[str, str]]:
    return [(lang.strip().lower(), body) for lang, body in FENCE.findall(text)]


def _classify(lang: str, body: str) -> tuple[list[str], list[tuple[str, str]]]:
    if lang == "text":
        return [], [("text fence", "sample output, not a command")]
    commands: list[str] = []
    skipped: list[tuple[str, str]] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("tk "):
            commands.append(line)
        else:
            skipped.append((line, "not a tk command"))
    return commands, skipped


class ReadmeFenceTests(unittest.TestCase):
    def test_valid_tk_lines_run_and_prose_is_skipped(self):
        text = README.read_text(encoding="utf-8")
        commands: list[str] = []
        skipped: list[tuple[str, str]] = []
        for lang, body in _fences(text):
            found, held = _classify(lang, body)
            commands.extend(found)
            skipped.extend(held)
        self.assertEqual(
            commands,
            ["tk find wiki", "tk run wiki.lint --path wiki"],
        )
        reasons = {line: why for line, why in skipped}
        self.assertEqual(reasons["text fence"], "sample output, not a command")
        self.assertIn("git clone https://github.com/ASabale/agent-toolkit.git", reasons)
        self.assertIn("npx skills add ASabale/agent-toolkit", reasons)
        self.assertIn("git -C <repo> config core.hooksPath .githooks", reasons)
        env = os.environ.copy()
        env["TK_NO_TELEMETRY"] = "1"
        for command in commands:
            proc = subprocess.run(
                [str(ROOT / "tk"), *command.split()[1:]],
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
