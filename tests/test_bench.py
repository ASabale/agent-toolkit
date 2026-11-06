"""Offline MCP-vs-tk benchmark: provenance gates and live tk idle bytes."""

from __future__ import annotations

import json
import os
import shutil
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


def _tk_by_task(stdout: str) -> dict[str, dict]:
    reports = json.loads(stdout)
    return {row["task"]: row["tk"] for row in reports}


def _ignore_checkout(directory: str, names: list[str]) -> set[str]:
    skipped = {name for name in names if name in {".git", "__pycache__", ".DS_Store", "state"}}
    if Path(directory).name == "bench":
        skipped.add("work")
    return skipped


def _pinned_path(bin_dir: Path) -> str:
    """PATH with this interpreter and no node.

    mcp-server-fetch's live example.com result is 271 bytes, or 246 when
    node is on PATH. The bench reads the fixture, and this pin keeps a
    checkout run from depending on whichever node the machine has.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    link = bin_dir / "python3"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(Path(sys.executable).resolve())
    return os.pathsep.join([str(bin_dir), "/usr/bin", "/bin"])


def _run_checkout(root: Path, tmp: Path, path: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["TK_NO_TELEMETRY"] = "1"
    env["TMPDIR"] = str(tmp)
    env["PATH"] = path
    return subprocess.run(
        [sys.executable, str(root / "bench" / "mcp_vs_tk.py"), "--json"],
        capture_output=True,
        text=True,
        cwd=root,
        env=env,
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
            self.assertEqual(row["client"], "scripted")
            for side in ("mcp", "tk"):
                measured = row["productivity"][side]
                self.assertIsNone(measured["first_attempt_success"])
                self.assertIsNone(measured["recovery"])
                self.assertIsNone(measured["reliability"])
                self.assertIsNone(measured["policy_violations"])
                self.assertIsNone(measured["adapt_time_s"])
                self.assertEqual(
                    measured["tool_calls_per_success"],
                    row[side]["tool_call_count"],
                )
            self.assertIsNone(row["productivity"]["mcp"]["discovery_turns"])
            self.assertEqual(row["productivity"]["tk"]["discovery_turns"], 1)

    def test_tk_results_match_across_tmpdir_and_checkout(self) -> None:
        # Different lengths: equal-length absolute paths can hide the leak.
        with tempfile.TemporaryDirectory() as base:
            base_path = Path(base)
            short_tmp = base_path / "t"
            long_tmp = base_path / ("u" * 48)
            short_tmp.mkdir()
            long_tmp.mkdir()
            pinned = _pinned_path(base_path / "py")
            first = _run("--json", env={"TMPDIR": str(short_tmp), "PATH": pinned})
            second = _run("--json", env={"TMPDIR": str(long_tmp), "PATH": pinned})
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(_tk_by_task(first.stdout), _tk_by_task(second.stdout))
            self.assertFalse((ROOT / "bench" / "work").exists())

            short_root = base_path / "a"
            long_root = base_path / ("b" * 48) / "checkout"
            shutil.copytree(ROOT, short_root, ignore=_ignore_checkout, symlinks=True)
            shutil.copytree(ROOT, long_root, ignore=_ignore_checkout, symlinks=True)
            left = _run_checkout(short_root, short_tmp, pinned)
            right = _run_checkout(long_root, long_tmp, pinned)
        self.assertEqual(left.returncode, 0, left.stderr)
        self.assertEqual(right.returncode, 0, right.stderr)
        self.assertEqual(_tk_by_task(left.stdout), _tk_by_task(right.stdout))

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
