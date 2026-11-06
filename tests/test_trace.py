"""Best-effort execution trace, independent of telemetry and the audit log."""

from __future__ import annotations

import json
import os
import threading
import unittest
import uuid
from pathlib import Path

from lib.evolver import append_trace

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
