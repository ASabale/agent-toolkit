"""Chain preflight runs before any step process and links step traces."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib.runner import _chain_trace_start, run_chain


def _script(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _tool(name: str, path: Path, safety: str = "read-only", needs: list | None = None, args: list | None = None) -> dict:
    return {
        "name": name,
        "kind": "tool",
        "path": str(path),
        "safety": safety,
        "needs": needs or [],
        "example": f"tk run {name}",
        "args": args
        or [
            {
                "flag": "--id",
                "env_var": "TK_ARG_ID",
                "required": False,
                "type": "string",
                "description": "id",
                "default": None,
            }
        ],
    }


class _State:
    def __enter__(self) -> Path:
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


def _lines(root: Path, name: str) -> list[dict]:
    path = root / "state" / name
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class ChainPreflightTests(unittest.TestCase):
    def test_missing_bin_on_step_four_does_not_run_the_writer(self):
        """Named failure: a later declared bin used to start step 1."""
        with _State() as root:
            marker = root / "sentinel"
            tools = {}
            for index in range(1, 6):
                path = root / f"step{index}"
                _script(path, f"#!/bin/sh\ntouch {marker}\nprintf '%s\\n' '{{\"n\":{index}}}'\n")
                needs = ["tk-missing-bin-274"] if index == 4 else []
                safety = "mutating" if index == 1 else "read-only"
                tools[f"demo.step{index}"] = _tool(f"demo.step{index}", path, safety, needs)
            chain = {
                "kind": "chain",
                "name": "demo.five",
                "example": "tk run demo.five",
                "safety": "read-only",
                "args": [],
                "steps": [{"tool": f"demo.step{index}", "args": {}} for index in range(1, 6)],
            }
            with patch("lib.catalog.discover_catalog", return_value=tools):
                code, out, err = run_chain(root, chain, {})
            self.assertEqual(code, 1)
            self.assertEqual(out, "")
            payload = json.loads(err)
            self.assertEqual(payload["error"], "chain_preflight_failed")
            self.assertIn("tk-missing-bin-274", payload["why"])
            self.assertNotIn("n", out)
            self.assertFalse(marker.exists())
            trace = _lines(root, "trace.jsonl")
            self.assertEqual([row["kind"] for row in trace], ["chain", "chain"])
            self.assertEqual(trace[1]["outcome"], "preflight")
            self.assertEqual(trace[0]["run_id"], trace[1]["run_id"])
            audit = _lines(root, "audit.jsonl")
            self.assertEqual([row["decision"] for row in audit], ["preflight"])

    def test_ambiguous_step_four_does_not_run_step_one(self):
        with _State() as root:
            marker = root / "sentinel"
            tools_dir = root / "tools"
            tools_dir.mkdir()
            for leaf in ("a", "b"):
                _script(
                    tools_dir / leaf,
                    "#!/bin/sh\n# @tk-name: demo.ambiguous\n# @tk-summary: one\n"
                    "# @tk-safety: read-only\n# @tk-example: tk run demo.ambiguous\n",
                )
            path = root / "step1"
            _script(path, f"#!/bin/sh\ntouch {marker}\nprintf '%s\\n' '{{}}'\n")
            tools = {
                "demo.step1": _tool("demo.step1", path, "mutating", []),
                "demo.ambiguous": _tool("demo.ambiguous", path, "read-only", []),
            }
            chain = {
                "kind": "chain",
                "name": "demo.five",
                "example": "tk run demo.five",
                "args": [],
                "steps": [{"tool": "demo.step1", "args": {}}]
                + [{"tool": "demo.step1", "args": {}}] * 2
                + [{"tool": "demo.ambiguous", "args": {}}]
                + [{"tool": "demo.step1", "args": {}}],
            }
            with patch("lib.catalog.discover_catalog", return_value=tools):
                code, out, err = run_chain(root, chain, {})
            self.assertEqual(code, 1, err)
            self.assertEqual(json.loads(err)["error"], "chain_preflight_failed")
            self.assertIn("duplicate_name", json.loads(err)["why"])
            self.assertFalse(marker.exists())
            self.assertEqual([row["kind"] for row in _lines(root, "trace.jsonl")], ["chain", "chain"])

    def test_prev_missing_runs_step_one_then_stops(self):
        with _State() as root:
            first = root / "first"
            second = root / "second"
            _script(first, "#!/bin/sh\nprintf '%s\\n' '{\"ok\":true}'\n")
            _script(second, "#!/bin/sh\nprintf '%s\\n' '{\"ran\":true}'\n")
            tools = {
                "demo.first": _tool("demo.first", first),
                "demo.second": _tool(
                    "demo.second",
                    second,
                    args=[
                        {
                            "flag": "--id",
                            "env_var": "TK_ARG_ID",
                            "required": True,
                            "type": "string",
                            "description": "id",
                            "default": None,
                        }
                    ],
                ),
            }
            chain = {
                "kind": "chain",
                "name": "demo.prev",
                "example": "tk run demo.prev",
                "args": [],
                "steps": [
                    {"tool": "demo.first", "args": {}},
                    {"tool": "demo.second", "args": {"--id": "$prev.missing"}},
                ],
            }
            with patch("lib.catalog.discover_catalog", return_value=tools):
                code, out, err = run_chain(root, chain, {})
            self.assertEqual(code, 1, err)
            self.assertEqual(json.loads(err)["error"], "unresolved_reference")
            self.assertNotIn("ran", out)
            trace = _lines(root, "trace.jsonl")
            chain_rows = [row for row in trace if row["kind"] == "chain"]
            self.assertEqual(chain_rows[1]["outcome"], "partial")
            parent = chain_rows[0]["run_id"]
            children = [row for row in trace if row["kind"] == "tool"]
            self.assertTrue(children)
            self.assertTrue(all(row["parent_run_id"] == parent for row in children))
            self.assertEqual(children[0]["phase"], "start")
            self.assertEqual(children[-1]["outcome"], "failed")

    def test_skipped_requires_does_not_stop_the_chain(self):
        with _State() as root:
            path = root / "echo"
            _script(path, "#!/bin/sh\nprintf '%s\\n' '{\"ok\":true}'\n")
            tools = {"demo.echo": _tool("demo.echo", path)}
            chain = {
                "kind": "chain",
                "name": "demo.skip",
                "example": "tk run demo.skip",
                "requires": ["shell:true"],
                "args": [],
                "steps": [{"tool": "demo.echo", "args": {}}],
            }
            with patch("lib.catalog.discover_catalog", return_value=tools):
                code, out, err = run_chain(root, chain, {})
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["ok"], True)
            self.assertEqual(_lines(root, "trace.jsonl")[-1]["outcome"], "ok")

    def test_dry_run_finishes_dry_run_for_chain_and_steps(self):
        with _State() as root:
            marker = root / "sentinel"
            path = root / "write"
            _script(
                path,
                "#!/bin/sh\n"
                "if [ \"$TK_DRY_RUN\" = 1 ]; then printf '%s\\n' '{\"dry_run\":true}'; exit 0; fi\n"
                f"touch {marker}\nprintf '%s\\n' '{{}}'\n",
            )
            tools = {"demo.write": _tool("demo.write", path, "mutating")}
            chain = {
                "kind": "chain",
                "name": "demo.dry",
                "example": "tk run demo.dry",
                "args": [],
                "steps": [{"tool": "demo.write", "args": {}}],
            }
            with patch("lib.catalog.discover_catalog", return_value=tools):
                code, out, err = run_chain(root, chain, {}, confirmed=False)
            self.assertEqual(code, 0, err)
            self.assertTrue(json.loads(out)["dry_run"])
            self.assertFalse(marker.exists())
            trace = _lines(root, "trace.jsonl")
            finishes = [row for row in trace if row["phase"] == "finish"]
            self.assertEqual({row["outcome"] for row in finishes}, {"dry_run"})

    def test_read_only_chain_has_trace_and_no_writer_audit(self):
        with _State() as root:
            path = root / "echo"
            _script(path, "#!/bin/sh\nprintf '%s\\n' '{\"ok\":true}'\n")
            tools = {"demo.echo": _tool("demo.echo", path)}
            chain = {
                "kind": "chain",
                "name": "demo.ro",
                "example": "tk run demo.ro",
                "args": [],
                "steps": [{"tool": "demo.echo", "args": {}}],
            }
            with patch("lib.catalog.discover_catalog", return_value=tools):
                code, _out, err = run_chain(root, chain, {})
            self.assertEqual(code, 0, err)
            trace = _lines(root, "trace.jsonl")
            self.assertGreaterEqual(len(trace), 2)
            self.assertEqual(_lines(root, "audit.jsonl"), [])
            parent = next(row["run_id"] for row in trace if row["kind"] == "chain")
            self.assertTrue(
                all(row["parent_run_id"] == parent for row in trace if row["kind"] == "tool")
            )

    def test_install_then_use_is_rejected_before_step_one(self):
        with _State() as root:
            marker = root / "sentinel"
            installer = root / "install"
            user = root / "use"
            _script(installer, f"#!/bin/sh\ntouch {marker}\nprintf '%s\\n' '{{}}'\n")
            _script(user, "#!/bin/sh\nprintf '%s\\n' '{\"stdout\":\"from-step-2\"}'\n")
            tools = {
                "demo.install": _tool("demo.install", installer, "mutating"),
                "demo.use": _tool("demo.use", user, needs=["tk-missing-bin-274"]),
            }
            chain = {
                "kind": "chain",
                "name": "demo.install-use",
                "example": "tk run demo.install-use",
                "args": [],
                "steps": [
                    {"tool": "demo.install", "args": {}},
                    {"tool": "demo.use", "args": {}},
                ],
            }
            with patch("lib.catalog.discover_catalog", return_value=tools):
                code, out, err = run_chain(root, chain, {})
            self.assertEqual(code, 1)
            self.assertEqual(out, "")
            self.assertNotIn("from-step-2", err)
            self.assertEqual(json.loads(err)["error"], "chain_preflight_failed")
            self.assertFalse(marker.exists())

    def test_unmatched_chain_start_when_finish_is_not_called(self):
        with _State() as root:
            _chain_trace_start(root, {"name": "demo.cut"}, "11111111-1111-1111-1111-111111111111", 2)
            trace = _lines(root, "trace.jsonl")
            self.assertEqual(len(trace), 1)
            self.assertEqual(trace[0]["phase"], "start")
            self.assertIsNone(trace[0]["outcome"])

    def test_preflight_audit_failure_reports_audit_failed(self):
        with _State() as root:
            path = root / "write"
            _script(path, "#!/bin/sh\nprintf '%s\\n' '{{}}'\n")
            tools = {"demo.write": _tool("demo.write", path, "mutating", ["tk-missing-bin-274"])}
            chain = {
                "kind": "chain",
                "name": "demo.audit",
                "example": "tk run demo.audit",
                "args": [],
                "steps": [{"tool": "demo.write", "args": {}}],
            }
            with patch("lib.catalog.discover_catalog", return_value=tools), patch(
                "lib.runner.append_audit", return_value=False
            ):
                code, _out, err = run_chain(root, chain, {})
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(err)["error"], "audit_failed")
            self.assertEqual(_lines(root, "trace.jsonl")[-1]["outcome"], "preflight")
