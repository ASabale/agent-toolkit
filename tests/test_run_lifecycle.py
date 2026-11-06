"""One run_id per run_tool call, with writer authorization and a terminal audit."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import stat
import unittest
from pathlib import Path

from lib.evolver import append_audit
from lib.runner import run_tool

ROOT = Path(__file__).resolve().parents[1]


def _tool(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _item(path: Path, safety: str) -> dict:
    return {
        "name": "demo.touch",
        "path": str(path),
        "safety": safety,
        "args": [],
        "example": "tk run demo.touch",
        "kind": "tool",
    }


class _State:
    def __enter__(self) -> Path:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self._root = Path(self._tmp.name)
        self._previous = os.environ.get("TK_STATE_DIR")
        os.environ["TK_STATE_DIR"] = str(self._root / "state")
        return self._root

    def __exit__(self, *_args) -> None:
        if self._previous is None:
            os.environ.pop("TK_STATE_DIR", None)
        else:
            os.environ["TK_STATE_DIR"] = self._previous
        self._tmp.cleanup()


class RunLifecycleTests(unittest.TestCase):
    def test_writer_yes_records_authorization_then_finish_with_one_run_id(self):
        with _State() as root:
            marker = root / "sentinel"
            tool = root / "touch"
            _tool(
                tool,
                "#!/bin/bash\n"
                "printf '%s\\n' '{\"ok\":true}'\n"
                f"touch {marker}\n",
            )
            code, out, err = run_tool(root, _item(tool, "mutating"), {}, confirmed=True)
            self.assertEqual(code, 0, err)
            self.assertTrue(marker.exists())
            audit = [
                json.loads(line)
                for line in (root / "state" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            trace = [
                json.loads(line)
                for line in (root / "state" / "trace.jsonl").read_text(encoding="utf-8").splitlines()
            ]
        self.assertEqual([row["decision"] for row in audit], ["allow", "finish"])
        self.assertEqual(audit[0]["run_id"], audit[1]["run_id"])
        self.assertEqual(audit[1]["process_exit"], 0)
        self.assertEqual(audit[1]["toolkit_exit"], 0)
        self.assertEqual(audit[1]["isolation"], "none")
        self.assertEqual([row["phase"] for row in trace], ["start", "finish"])
        self.assertEqual(trace[1]["outcome"], "ok")
        self.assertEqual(trace[0]["run_id"], audit[0]["run_id"])
        blob = json.dumps({"audit": audit, "trace": trace, "stdout": out})
        self.assertNotIn("TK_ARG", blob)
        self.assertNotIn(str(marker), blob)

    def test_read_only_tool_traces_without_an_audit_file(self):
        with _State() as root:
            tool = root / "look"
            _tool(tool, "#!/bin/bash\nprintf '%s\\n' '{\"ok\":true}'\n")
            code, _out, err = run_tool(root, _item(tool, "read-only"), {}, confirmed=False)
            self.assertEqual(code, 0, err)
            phases = [
                json.loads(line)["phase"]
                for line in (root / "state" / "trace.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(phases, ["start", "finish"])
            self.assertFalse((root / "state" / "audit.jsonl").exists())

    def test_dry_run_finish_outcome_is_dry_run(self):
        with _State() as root:
            marker = root / "sentinel"
            tool = root / "touch"
            _tool(
                tool,
                "#!/bin/bash\n"
                "if [[ \"${TK_DRY_RUN:-0}\" == \"1\" ]]; then\n"
                "  printf '%s\\n' '{\"dry_run\":true,\"plan\":[\"touch\"]}'\n"
                "  exit 0\n"
                "fi\n"
                f"touch {marker}\n"
                "printf '%s\\n' '{\"ok\":true}'\n",
            )
            code, _out, err = run_tool(root, _item(tool, "mutating"), {}, confirmed=False)
            self.assertEqual(code, 0, err)
            self.assertFalse(marker.exists())
            finish = json.loads((root / "state" / "trace.jsonl").read_text(encoding="utf-8").splitlines()[-1])
            auth = json.loads((root / "state" / "audit.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(finish["outcome"], "dry_run")
        self.assertEqual(finish["phase"], "finish")
        self.assertEqual(auth["decision"], "dry_run")

    def test_unwritable_audit_does_not_start_the_writer(self):
        with _State() as root:
            marker = root / "sentinel"
            tool = root / "touch"
            _tool(tool, "#!/bin/bash\nprintf '%s\\n' '{\"ok\":true}'\n" f"touch {marker}\n")
            blocked = root / "state"
            blocked.write_text("not-a-directory", encoding="utf-8")
            os.environ["TK_STATE_DIR"] = str(blocked)
            code, _out, err = run_tool(root, _item(tool, "mutating"), {}, confirmed=True)
            self.assertEqual(code, 1)
            self.assertIn("audit_failed", err)
            self.assertFalse(marker.exists())

    def test_terminal_audit_failure_keeps_the_successful_writer(self):
        with _State() as root:
            marker = root / "sentinel"
            tool = root / "touch"
            _tool(tool, "#!/bin/bash\nprintf '%s\\n' '{\"ok\":true}'\n" f"touch {marker}\n")
            calls = {"n": 0}
            real = append_audit

            def once(root_dir, record):
                calls["n"] += 1
                if calls["n"] == 1:
                    return real(root_dir, record)
                return False

            import lib.runner as runner

            original = runner.append_audit
            runner.append_audit = once
            try:
                code, _out, err = run_tool(root, _item(tool, "mutating"), {}, confirmed=True)
            finally:
                runner.append_audit = original
            self.assertEqual(code, 0, err)
            self.assertTrue(marker.exists())
            payload = json.loads(err)
            self.assertIs(payload["audit_incomplete"], True)
            audit = [
                json.loads(line)
                for line in (root / "state" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
            ]
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["decision"], "allow")

    def test_nonwritable_trace_does_not_block_a_read_only_tool(self):
        with _State() as root:
            marker = root / "sentinel"
            tool = root / "look"
            _tool(tool, "#!/bin/bash\nprintf '%s\\n' '{\"ok\":true}'\n" f"touch {marker}\n")
            blocked = root / "state"
            blocked.write_text("not-a-directory", encoding="utf-8")
            os.environ["TK_STATE_DIR"] = str(blocked)
            code, _out, err = run_tool(root, _item(tool, "read-only"), {}, confirmed=False)
            self.assertEqual(code, 0, err)
            self.assertTrue(marker.exists())

    def test_invalid_json_records_process_exit_zero_and_toolkit_exit_one(self):
        with _State() as root:
            tool = root / "bad"
            _tool(tool, "#!/bin/bash\nprintf '%s\\n' 'not-json'\n")
            code, _out, err = run_tool(root, _item(tool, "read-only"), {}, confirmed=True)
            self.assertEqual(code, 1)
            self.assertIn("invalid_output", err)
            finish = json.loads((root / "state" / "trace.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(finish["process_exit"], 0)
        self.assertEqual(finish["toolkit_exit"], 1)
        self.assertEqual(finish["phase"], "finish")

    def test_cli_without_yes_passes_confirmed_false(self):
        loader = importlib.machinery.SourceFileLoader("tk_cli", str(ROOT / "tk"))
        spec = importlib.util.spec_from_loader("tk_cli", loader)
        tk_cli = importlib.util.module_from_spec(spec)
        loader.exec_module(tk_cli)
        seen = {}

        class Catalog:
            def resolve_named_item(self, _root, name):
                return "one", {"name": name, "kind": "tool", "safety": "mutating"}, []

        class Runner:
            def parse_cli_flags(self, _argv, _item):
                return {}, False, []

            def confirm_id_from_argv(self, _argv):
                return None

            def run_tool(self, *_args, **kwargs):
                seen["confirmed"] = kwargs["confirmed"]
                return 0, "{}", ""

        code = tk_cli._cmd_run(Catalog(), Runner(), None, "demo.touch", ["--path", "x"], chains_only=False)
        self.assertEqual(code, 0)
        self.assertIs(seen["confirmed"], False)
