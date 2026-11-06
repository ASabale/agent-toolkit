"""Default tk find cap and self-healing hint on zero matches."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.catalog import discover_catalog, find_items  # noqa: E402

TK = ROOT / "tk"


def _run(*args: str, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(
        [sys.executable, str(TK), *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=run_env,
        check=False,
    )


def _item_names(stdout: str) -> list[str]:
    return [
        line.split(" ", 1)[0]
        for line in stdout.splitlines()
        if line and not line.startswith(" ")
    ]


def _load_tk():
    loader = SourceFileLoader("tk_dispatcher", str(TK))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class _EmptyCatalog:
    def find_items(self, root_dir, query="", limit=None, namespace=None):
        return []

    def discover_catalog(self, root_dir):
        return {"git.diff-digest": {"name": "git.diff-digest"}}

    def resolve_named_item(self, root_dir, name):
        return "none", None, []

    def format_find_output(self, items):
        return ""


class _Evolver:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def log_event(self, root_dir, event_type, payload):
        self.events.append({"event": event_type, **payload})


class FindBudgetTests(unittest.TestCase):
    def test_nonempty_query_defaults_to_five_items(self) -> None:
        unbounded = find_items(ROOT, "git diff")
        self.assertGreater(len(unbounded), 5)
        proc = _run("find", "git diff")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        names = _item_names(proc.stdout)
        self.assertEqual(len(names), 5)
        self.assertEqual(len(proc.stdout.splitlines()), 10)
        self.assertEqual(names, [item["name"] for item in unbounded[:5]])
        self.assertEqual(proc.stderr.strip(), "")

    def test_explicit_limit_overrides_default_cap(self) -> None:
        unbounded = find_items(ROOT, "git diff")
        proc = _run("find", "git diff", "--limit", "20")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        names = _item_names(proc.stdout)
        self.assertEqual(names, [item["name"] for item in unbounded])
        self.assertGreater(len(names), 5)

    def test_empty_query_lists_full_catalog(self) -> None:
        catalog = discover_catalog(ROOT)
        proc = _run("find")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        names = _item_names(proc.stdout)
        self.assertEqual(names, sorted(catalog))
        self.assertGreater(len(names), 5)
        self.assertEqual(len(proc.stdout.splitlines()), 2 * len(catalog))

    def test_zero_matches_prints_find_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _run(
                "find",
                "zzzz",
                env={"TK_NO_TELEMETRY": "", "TK_STATE_DIR": tmp},
            )
            events_path = Path(tmp) / "events.jsonl"
            events = [
                json.loads(line)
                for line in events_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")
        lines = [line for line in proc.stderr.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertEqual(
            payload,
            {
                "error": "no_match",
                "why": "no tool or chain matches 'zzzz'",
                "fix": "tk find",
            },
        )
        misses = [event for event in events if event.get("event") == "search_miss"]
        self.assertEqual(len(misses), 1)
        self.assertEqual(misses[0]["query"], "zzzz")

    def test_namespace_token_miss_hint(self) -> None:
        tk = _load_tk()
        evolver = _Evolver()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = tk._cmd_find(_EmptyCatalog(), evolver, ["git", "zzzz"])
        self.assertEqual(code, 0)
        self.assertEqual(stdout.getvalue(), "")
        lines = [line for line in stderr.getvalue().splitlines() if line.strip()]
        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertEqual(
            payload,
            {
                "error": "no_match",
                "why": "no tool or chain matches 'git zzzz'",
                "fix": "tk find --namespace git",
            },
        )
        self.assertEqual(evolver.events[0]["event"], "search_miss")
        self.assertEqual(evolver.events[0]["query"], "git zzzz")

    def test_namespace_token_miss_hint_via_cli(self) -> None:
        # Catalog scoring is OR-per-token, so live `tk find git zzzz` still
        # matches git.* tools. Pin --namespace json to force a miss while
        # keeping the first query token as an existing namespace.
        with tempfile.TemporaryDirectory() as tmp:
            proc = _run(
                "find",
                "git",
                "zzzz",
                "--namespace",
                "json",
                env={"TK_NO_TELEMETRY": "", "TK_STATE_DIR": tmp},
            )
            events_path = Path(tmp) / "events.jsonl"
            events = [
                json.loads(line)
                for line in events_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")
        payload = json.loads(proc.stderr)
        self.assertEqual(payload["error"], "no_match")
        self.assertEqual(payload["why"], "no tool or chain matches 'git zzzz'")
        self.assertEqual(payload["fix"], "tk find --namespace git")
        misses = [event for event in events if event.get("event") == "search_miss"]
        self.assertEqual(len(misses), 1)
        self.assertEqual(misses[0]["query"], "git zzzz")


if __name__ == "__main__":
    unittest.main()
