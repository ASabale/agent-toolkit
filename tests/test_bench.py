"""Offline MCP-vs-tk benchmark: provenance gates and live tk idle bytes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "bench" / "mcp_vs_tk.py"
SKILL_CANDIDATES = (
    ROOT / "skills" / "agent-toolkit" / "SKILL.md",
    ROOT / "skills" / "toolkit" / "SKILL.md",
)


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    merged["TK_NO_TELEMETRY"] = "1"
    return subprocess.run(
        [sys.executable, str(BENCH), *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=merged,
        check=False,
    )


def _skill_bytes() -> int:
    for path in SKILL_CANDIDATES:
        if path.is_file():
            return path.stat().st_size
    raise FileNotFoundError("SKILL.md")


class BenchTests(unittest.TestCase):
    def test_json_emits_one_object_per_task_and_tk_idle_matches_skill(self) -> None:
        started = time.perf_counter()
        proc = _run("--json")
        elapsed = time.perf_counter() - started
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertLess(elapsed, 10)
        reports = json.loads(proc.stdout)
        self.assertIsInstance(reports, list)
        self.assertEqual(len(reports), 3)
        skill = _skill_bytes()
        tasks = {row["task"] for row in reports}
        self.assertEqual(
            tasks,
            {
                "why is CI red on PR N",
                "show schema + 5 rows of table T",
                "read the text of URL U",
            },
        )
        for row in reports:
            self.assertTrue(row["source"])
            self.assertTrue(row["server_version"])
            self.assertTrue(row["captured_on"])
            self.assertEqual(row["tk"]["idle_bytes"], skill)
            self.assertEqual(row["tk"]["est_tokens_note"], "bytes/4 estimate")
            self.assertEqual(row["mcp"]["est_tokens_note"], "bytes/4 estimate")
            self.assertGreater(row["mcp"]["idle_bytes"], 0)
            self.assertGreaterEqual(row["mcp"]["output_bytes"], 0)
            self.assertGreater(row["tk"]["discovery_bytes"], 0)
            self.assertGreater(row["tk"]["output_bytes"], 0)
            self.assertGreater(row["tk"]["tool_call_count"], 0)
            self.assertEqual(
                row["tk"]["est_tokens"],
                (
                    row["tk"]["idle_bytes"]
                    + row["tk"]["discovery_bytes"]
                    + row["tk"]["output_bytes"]
                )
                // 4,
            )

    def test_refuses_fixture_missing_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "no_source.json"
            bad.write_text(
                json.dumps(
                    {
                        "task": "missing keys",
                        "server_version": "0",
                        "captured_on": "2026-11-03",
                        "mcp_tools_list": {"tools": []},
                        "mcp_results": [],
                    }
                ),
                encoding="utf-8",
            )
            proc = _run("--json", "--fixtures", tmp)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        payload = json.loads(proc.stderr)
        self.assertEqual(payload["error"], "missing_provenance")
        self.assertIn("source", payload["why"])
        self.assertIn("fix", payload)
        self.assertIn("source", payload["fix"])


if __name__ == "__main__":
    unittest.main()
