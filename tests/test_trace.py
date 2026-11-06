"""Best-effort execution trace, independent of telemetry and the audit log."""

from __future__ import annotations

import json
import os
import stat
import threading
import unittest
import uuid
from pathlib import Path

from lib.catalog import discover_catalog
from lib.evolver import append_trace
from lib.runner import run_chain, run_tool

_SECRET = "ghp_" + "a" * 36


class TraceTests(unittest.TestCase):
    def test_start_and_finish_match_the_schema(self):
        with self._root() as root:
            run_id = str(uuid.uuid4())
            append_trace(root, {"phase": "start", "run_id": run_id, "name": "demo.touch", "kind": "tool"})
            append_trace(
                root,
                {
                    "phase": "finish",
                    "run_id": run_id,
                    "name": "demo.touch",
                    "kind": "tool",
                    "outcome": "ok",
                    "process_exit": 0,
                    "toolkit_exit": 0,
                    "duration_ms": 4,
                },
            )
            rows = self._rows(root)
        self.assertEqual(len(rows), 2)
        start, finish = rows
        for row in rows:
            uuid.UUID(row["event_id"])
            uuid.UUID(row["run_id"])
            self.assertEqual(row["schema_version"], 1)
            self.assertTrue(row["ts"].endswith("+00:00"))
            self.assertEqual(row["name"], "demo.touch")
            self.assertEqual(row["kind"], "tool")
            self.assertIsNone(row["parent_run_id"])
        self.assertEqual(start["phase"], "start")
        self.assertIsNone(start["outcome"])
        self.assertEqual(finish["phase"], "finish")
        self.assertEqual(finish["outcome"], "ok")
        self.assertEqual(finish["process_exit"], 0)
        self.assertEqual(finish["toolkit_exit"], 0)
        self.assertEqual(finish["duration_ms"], 4)
        self.assertEqual(start["run_id"], finish["run_id"])

    def test_two_threads_write_two_parseable_lines(self):
        with self._root() as root:
            barrier = threading.Barrier(2)

            def write() -> None:
                barrier.wait(timeout=5)
                append_trace(root, {"phase": "finish", "name": "demo.touch", "kind": "tool", "outcome": "ok"})

            threads = [threading.Thread(target=write) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)
            rows = self._rows(root)
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["outcome"] for row in rows}, {"ok"})

    def test_writes_when_telemetry_is_disabled(self):
        previous = os.environ.get("TK_NO_TELEMETRY")
        os.environ["TK_NO_TELEMETRY"] = "1"
        try:
            with self._root() as root:
                append_trace(root, {"phase": "start", "name": "demo.touch", "kind": "tool"})
                rows = self._rows(root)
        finally:
            if previous is None:
                os.environ.pop("TK_NO_TELEMETRY", None)
            else:
                os.environ["TK_NO_TELEMETRY"] = previous
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["phase"], "start")

    def test_non_writable_trace_path_is_swallowed(self):
        with self._root() as root:
            blocked = root / "state"
            blocked.write_text("not-a-directory", encoding="utf-8")
            os.environ["TK_STATE_DIR"] = str(blocked)
            append_trace(root, {"phase": "start", "name": "demo.touch", "kind": "tool"})
        self.assertFalse(blocked.is_dir())

    def test_secret_shaped_flag_value_is_not_stored(self):
        with self._root() as root:
            append_trace(
                root,
                {
                    "phase": "finish",
                    "name": "demo.touch",
                    "kind": "tool",
                    "outcome": "failed",
                    "--token": _SECRET,
                    "args": {"password": _SECRET},
                },
            )
            text = (root / "state" / "trace.jsonl").read_text(encoding="utf-8")
        self.assertNotIn(_SECRET, text)
        self.assertNotIn("--token", text)
        self.assertNotIn("password", text)

    def test_stdout_text_is_not_stored(self):
        secret_out = "stdout-marker-" + _SECRET
        with self._root() as root:
            append_trace(
                root,
                {
                    "phase": "finish",
                    "name": "demo.touch",
                    "kind": "tool",
                    "outcome": "ok",
                    "stdout": secret_out,
                    "stderr": "stderr-marker",
                    "command": "echo " + _SECRET,
                },
            )
            text = (root / "state" / "trace.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("stdout-marker", text)
        self.assertNotIn("stderr-marker", text)
        self.assertNotIn(_SECRET, text)
        self.assertNotIn("echo", text)

    def test_chain_children_carry_step_index_and_count(self):
        with self._root() as root:
            self._tool(root, "fixture.ok", "printf '%s\\n' '{\"ok\":true}'\n")
            self._chain(root, "fixture.ship", ["fixture.ok", "fixture.ok"])
            catalog = discover_catalog(root)
            code, _out, err = run_chain(root, catalog["fixture.ship"], {})
            self.assertEqual(code, 0, err)
            rows = self._rows(root)
        parent = self._chain_run(rows, "fixture.ship")
        children = self._child_runs(rows, parent)
        self.assertEqual(len(children), 2)
        for index, run_id in enumerate(children, start=1):
            phases = [row for row in rows if row["run_id"] == run_id]
            self.assertEqual({row["phase"] for row in phases}, {"start", "finish"})
            for row in phases:
                self.assertEqual(row["step_index"], index)
                self.assertEqual(row["step_count"], 2)
                self.assertEqual(row["parent_run_id"], parent)
                self.assertEqual(row["name"], "fixture.ok")

    def test_same_tool_twice_has_two_child_run_ids(self):
        with self._root() as root:
            self._tool(root, "fixture.echo", "printf '%s\\n' '{\"ok\":true}'\n")
            self._chain(root, "fixture.twice", ["fixture.echo", "fixture.echo"])
            catalog = discover_catalog(root)
            code, _out, err = run_chain(root, catalog["fixture.twice"], {})
            self.assertEqual(code, 0, err)
            rows = self._rows(root)
        children = self._child_runs(rows, self._chain_run(rows, "fixture.twice"))
        self.assertEqual(len(children), 2)
        self.assertNotEqual(children[0], children[1])
        indexes = []
        for run_id in children:
            finish = next(row for row in rows if row["run_id"] == run_id and row["phase"] == "finish")
            indexes.append(finish["step_index"])
        self.assertEqual(indexes, [1, 2])

    def test_first_step_failure_records_only_that_child(self):
        with self._root() as root:
            self._tool(root, "fixture.bad", "exit 3\n")
            self._tool(root, "fixture.later", "printf '%s\\n' '{\"ok\":true}'\n")
            self._chain(root, "fixture.stop", ["fixture.bad", "fixture.later"])
            catalog = discover_catalog(root)
            code, _out, err = run_chain(root, catalog["fixture.stop"], {})
            self.assertEqual(code, 3, err)
            rows = self._rows(root)
        parent = self._chain_run(rows, "fixture.stop")
        children = self._child_runs(rows, parent)
        self.assertEqual(len(children), 1)
        child = [row for row in rows if row["run_id"] == children[0]]
        self.assertEqual({row["name"] for row in child}, {"fixture.bad"})
        for row in child:
            self.assertEqual(row["step_index"], 1)
            self.assertEqual(row["step_count"], 2)
        self.assertFalse(any(row["name"] == "fixture.later" for row in rows))

    def test_later_step_failure_is_partial_with_both_indexes(self):
        with self._root() as root:
            self._tool(root, "fixture.ok", "printf '%s\\n' '{\"ok\":true}'\n")
            self._tool(root, "fixture.bad", "exit 5\n")
            self._chain(root, "fixture.partial", ["fixture.ok", "fixture.bad"])
            catalog = discover_catalog(root)
            code, _out, err = run_chain(root, catalog["fixture.partial"], {})
            self.assertEqual(code, 5, err)
            rows = self._rows(root)
        parent = self._chain_run(rows, "fixture.partial")
        chain_finish = next(
            row for row in rows if row["run_id"] == parent and row["phase"] == "finish"
        )
        self.assertEqual(chain_finish["outcome"], "partial")
        children = self._child_runs(rows, parent)
        self.assertEqual(len(children), 2)
        by_name = {}
        for run_id in children:
            finish = next(row for row in rows if row["run_id"] == run_id and row["phase"] == "finish")
            by_name[finish["name"]] = finish["step_index"]
            self.assertEqual(finish["step_count"], 2)
        self.assertEqual(by_name, {"fixture.ok": 1, "fixture.bad": 2})

    def test_direct_tool_run_leaves_step_fields_null(self):
        with self._root() as root:
            self._tool(root, "fixture.ok", "printf '%s\\n' '{\"ok\":true}'\n")
            catalog = discover_catalog(root)
            code, _out, err = run_tool(root, catalog["fixture.ok"], {})
            self.assertEqual(code, 0, err)
            rows = self._rows(root)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertIsNone(row["step_index"])
            self.assertIsNone(row["step_count"])
            self.assertIsNone(row["parent_run_id"])

    def test_trace_write_error_keeps_the_tool_exit_code(self):
        with self._root() as root:
            self._tool(root, "fixture.ok", "printf '%s\\n' '{\"ok\":true}'\n")
            blocked = root / "state"
            blocked.write_text("not-a-directory", encoding="utf-8")
            os.environ["TK_STATE_DIR"] = str(blocked)
            catalog = discover_catalog(root)
            code, _out, err = run_tool(root, catalog["fixture.ok"], {})
        self.assertEqual(code, 0, err)
        self.assertFalse(blocked.is_dir())

    def _tool(self, root: Path, name: str, body: str) -> None:
        path = root / "tools" / "fixture" / name.split(".", 1)[1]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "#!/bin/sh\n"
            f"# @tk-name: {name}\n"
            "# @tk-summary: Trace fixture\n"
            "# @tk-safety: read-only\n"
            "# @tk-output: json | fixture payload\n"
            f"# @tk-example: tk run {name}\n"
            f"{body}",
            encoding="utf-8",
        )
        path.chmod(path.stat().st_mode | stat.S_IEXEC)

    def _chain(self, root: Path, name: str, tools: list[str]) -> None:
        path = root / "chains" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "kind": "chain",
                    "name": name,
                    "summary": "Trace fixture chain",
                    "safety": "read-only",
                    "steps": [{"tool": tool} for tool in tools],
                    "output": "json | fixture payload",
                    "example": f"tk run {name}",
                }
            ),
            encoding="utf-8",
        )

    def _chain_run(self, rows: list[dict], name: str) -> str:
        starts = [
            row["run_id"]
            for row in rows
            if row["name"] == name and row["kind"] == "chain" and row["phase"] == "start"
        ]
        self.assertEqual(len(starts), 1)
        return starts[0]

    def _child_runs(self, rows: list[dict], parent: str) -> list[str]:
        seen: list[str] = []
        for row in rows:
            if row.get("parent_run_id") != parent or row.get("phase") != "start":
                continue
            seen.append(row["run_id"])
        return seen

    def _root(self):
        return _State()

    def _rows(self, root: Path) -> list[dict]:
        path = root / "state" / "trace.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class _State:
    def __enter__(self) -> Path:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._previous = os.environ.get("TK_STATE_DIR")
        os.environ["TK_STATE_DIR"] = str(root / "state")
        return root

    def __exit__(self, *_args) -> None:
        if self._previous is None:
            os.environ.pop("TK_STATE_DIR", None)
        else:
            os.environ["TK_STATE_DIR"] = self._previous
        self._tmp.cleanup()
