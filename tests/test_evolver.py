"""Isolated unit tests for lib.evolver seams."""

from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.evolver import evolve_report, log_event, save_chain, save_tool  # noqa: E402


def _tool_script(*, name: str, summary: str, safety: str, body: str, arg_line: str | None = None) -> str:
    arg = f"# @tk-arg: {arg_line}\n" if arg_line else ""
    example_flags = ""
    if arg_line:
        flag = arg_line.split("|", 1)[0].strip()
        example_flags = f" {flag} example"
    return (
        "#!/usr/bin/env bash\n"
        f"# @tk-name: {name}\n"
        f"# @tk-summary: {summary}\n"
        f"# @tk-safety: {safety}\n"
        f"{arg}"
        "# @tk-output: json | Compact JSON result\n"
        f"# @tk-example: tk run {name}{example_flags}\n"
        "# @tk-verified: none\n"
        "\n"
        "set -euo pipefail\n"
        f"{body}\n"
    )


class EvolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_log_event_appends_jsonl_record(self) -> None:
        log_event(self.root, "search_miss", {"query": "deploy status"})
        log_event(self.root, "run", {"name": "demo.echo", "ok": True})

        lines = (self.root / "state" / "events.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        first = json.loads(lines[0])
        second = json.loads(lines[1])
        self.assertEqual(first["event"], "search_miss")
        self.assertEqual(first["query"], "deploy status")
        self.assertRegex(first["ts"], r"^\d{4}-\d{2}-\d{2}T")
        self.assertEqual(second["event"], "run")
        self.assertEqual(second["name"], "demo.echo")
        self.assertTrue(second["ok"])

    def test_log_event_never_raises_when_state_unwritable(self) -> None:
        # state/ exists but is a regular file: mkdir/open must be swallowed.
        blocked = self.root / "state"
        blocked.write_text("not a directory", encoding="utf-8")
        log_event(self.root, "search_miss", {"query": "x"})
        self.assertFalse((self.root / "state" / "events.jsonl").exists())

        # state/ is a read-only directory: the append must be swallowed.
        nested = self.root / "nested"
        nested.mkdir()
        readonly = nested / "state"
        readonly.mkdir()
        readonly.chmod(stat.S_IRUSR | stat.S_IXUSR)
        try:
            log_event(nested, "run_error", {"name": "demo.echo"})
            self.assertFalse((readonly / "events.jsonl").exists())
        finally:
            readonly.chmod(stat.S_IRWXU)

    def test_save_tool_writes_executable_header_and_logs(self) -> None:
        code, out, err = save_tool(
            self.root,
            "demo.echo",
            "Echo a token as JSON",
            "read-only",
            from_cmd="printf '%s\\n' \"{\\\"token\\\":\\\"$TK_ARG_TOKEN\\\"}\"",
            args_spec=["--token | required | string | Token to echo"],
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["name"], "demo.echo")
        self.assertEqual(payload["kind"], "tool")

        path = self.root / "tools" / "demo" / "echo"
        self.assertTrue(path.is_file())
        self.assertTrue(os.access(path, os.X_OK))
        text = path.read_text(encoding="utf-8")
        self.assertIn("# @tk-name: demo.echo", text)
        self.assertIn("# @tk-summary: Echo a token as JSON", text)
        self.assertIn("# @tk-safety: read-only", text)
        self.assertIn("# @tk-arg: --token | required | string | Token to echo", text)
        self.assertIn("# @tk-example: tk run demo.echo --token example", text)
        self.assertIn("# @tk-verified: none", text)
        self.assertIn("# @tk-output:", text)

        events = [
            json.loads(line)
            for line in (self.root / "state" / "events.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertTrue(any(event["event"] == "tool_saved" and event["name"] == "demo.echo" for event in events))

    def test_save_tool_rejects_bad_input_without_writing(self) -> None:
        code, out, err = save_tool(self.root, "demo.echo", "Missing source")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(json.loads(err)["error"], "missing_source")
        self.assertFalse((self.root / "tools").exists())

        code, out, err = save_tool(
            self.root,
            "../escape.tool",
            "Bad name",
            from_cmd="printf '%s\\n' '{\"ok\":true}'",
        )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "invalid_name")
        self.assertFalse((self.root / "escape.tool").exists())
        self.assertFalse((self.root / "tools").exists())

    def test_save_tool_quarantines_broken_drafts(self) -> None:
        broken = self.root / "broken.sh"
        broken.write_text("#!/usr/bin/env bash\nif [;\n", encoding="utf-8")
        code, out, err = save_tool(
            self.root,
            "demo.broken",
            "Syntax error body",
            file_path=str(broken),
        )
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        body = json.loads(err)
        self.assertEqual(body["error"], "check_failed")
        self.assertIn("fix", body)
        self.assertFalse((self.root / "tools" / "demo" / "broken").exists())

        claimed = self.root / "claimed.sh"
        claimed.write_text(
            _tool_script(
                name="demo.badjson",
                summary="Prints text instead of JSON",
                safety="read-only",
                body='printf "not-json\\n"',
            ),
            encoding="utf-8",
        )
        code, _, err = save_tool(
            self.root,
            "demo.badjson",
            "Prints text instead of JSON",
            file_path=str(claimed),
        )
        self.assertEqual(code, 1, err)
        self.assertFalse((self.root / "tools" / "demo" / "badjson").exists())
        self.assertFalse(any((self.root / "tools").rglob("*")))

    def test_save_tool_force_overwrites_only_valid_replacement(self) -> None:
        first, _, err = save_tool(
            self.root,
            "demo.echo",
            "First summary",
            from_cmd="printf '%s\\n' '{\"ok\":true}'",
        )
        self.assertEqual(first, 0, err)
        original = (self.root / "tools" / "demo" / "echo").read_text(encoding="utf-8")

        again, _, err = save_tool(
            self.root,
            "demo.echo",
            "Second summary",
            from_cmd="printf '%s\\n' '{\"ok\":true}'",
        )
        self.assertEqual(again, 1)
        self.assertEqual(json.loads(err)["error"], "already_exists")
        self.assertEqual((self.root / "tools" / "demo" / "echo").read_text(encoding="utf-8"), original)

        broken = self.root / "broken.sh"
        broken.write_text("#!/usr/bin/env bash\nif [;\n", encoding="utf-8")
        forced_bad, _, err = save_tool(
            self.root,
            "demo.echo",
            "Broken replacement",
            file_path=str(broken),
            force=True,
        )
        self.assertEqual(forced_bad, 1)
        self.assertEqual(json.loads(err)["error"], "check_failed")
        self.assertEqual((self.root / "tools" / "demo" / "echo").read_text(encoding="utf-8"), original)

        forced, out, err = save_tool(
            self.root,
            "demo.echo",
            "Replaced summary",
            from_cmd="printf '%s\\n' '{\"ok\":true}'",
            force=True,
        )
        self.assertEqual(forced, 0, err)
        self.assertIn("Replaced summary", (self.root / "tools" / "demo" / "echo").read_text(encoding="utf-8"))
        self.assertTrue(json.loads(out)["ok"])

    def test_save_chain_writes_and_rolls_back(self) -> None:
        code, _, err = save_tool(
            self.root,
            "demo.echo",
            "Echo a token as JSON",
            from_cmd="printf '%s\\n' '{\"ok\":true}'",
            args_spec=["--token | required | string | Token to echo"],
        )
        self.assertEqual(code, 0, err)

        code, out, err = save_chain(
            self.root,
            "demo.pipe",
            "Echo then stop",
            steps=[{"tool": "demo.echo", "args": {"token": "$input.token"}}],
            args=[{"flag": "--token", "required": True, "type": "string", "description": "Token"}],
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["kind"], "chain")
        chain_path = self.root / "chains" / "demo.pipe.json"
        saved = json.loads(chain_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["name"], "demo.pipe")
        self.assertEqual(saved["steps"][0]["tool"], "demo.echo")
        self.assertTrue(saved["example"].startswith("tk run demo.pipe"))
        self.assertIn("--token", saved["example"])
        events = (self.root / "state" / "events.jsonl").read_text(encoding="utf-8")
        self.assertIn("chain_saved", events)

        missing, _, err = save_chain(
            self.root,
            "demo.missing",
            "Calls a tool that does not exist",
            steps=[{"tool": "demo.absent"}],
        )
        self.assertEqual(missing, 1)
        self.assertEqual(json.loads(err)["error"], "check_failed")
        self.assertFalse((self.root / "chains" / "demo.missing.json").exists())

        original = chain_path.read_text(encoding="utf-8")
        refused, _, err = save_chain(
            self.root,
            "demo.pipe",
            "Nope",
            steps=[{"tool": "demo.echo"}],
        )
        self.assertEqual(json.loads(err)["error"], "already_exists")
        self.assertEqual(chain_path.read_text(encoding="utf-8"), original)

        bad_force, _, err = save_chain(
            self.root,
            "demo.pipe",
            "Broken overwrite",
            steps=[{"tool": "demo.absent"}],
            force=True,
        )
        self.assertEqual(bad_force, 1)
        self.assertEqual(json.loads(err)["error"], "check_failed")
        self.assertEqual(chain_path.read_text(encoding="utf-8"), original)

    def test_evolve_report_promotes_and_summarizes(self) -> None:
        ok, _, err = save_tool(
            self.root,
            "alpha.list-prs",
            "List pull requests for a repository",
            from_cmd="printf '%s\\n' '{\"ok\":true}'",
        )
        self.assertEqual(ok, 0, err)
        ok, _, err = save_tool(
            self.root,
            "alpha.show-prs",
            "Show pull requests for a repository",
            from_cmd="printf '%s\\n' '{\"ok\":true}'",
        )
        self.assertEqual(ok, 0, err)
        ok, _, err = save_tool(
            self.root,
            "beta.ship",
            "Ship a release branch",
            safety="mutating",
            from_cmd="printf '%s\\n' '{\"ok\":true}'",
        )
        self.assertEqual(ok, 0, err)

        failing = self.root / "tools" / "beta" / "crash"
        failing.parent.mkdir(parents=True, exist_ok=True)
        failing.write_text(
            _tool_script(
                name="beta.crash",
                summary="Always prints plain text",
                safety="read-only",
                body='printf "nope\\n"',
            ),
            encoding="utf-8",
        )
        failing.chmod(0o755)

        log_event(self.root, "search_miss", {"query": "deploy status"})
        log_event(self.root, "search_miss", {"query": "deploy status"})
        log_event(self.root, "search_miss", {"query": "budget"})
        log_event(self.root, "run", {"name": "alpha.list-prs"})
        log_event(self.root, "run_error", {"name": "beta.ship", "why": "rejected"})

        report = evolve_report(self.root, auto_promote=True)
        today = date.today().isoformat()

        self.assertEqual(report["promoted"], ["alpha.list-prs", "alpha.show-prs"])
        listed = (self.root / "tools" / "alpha" / "list-prs").read_text(encoding="utf-8")
        shown = (self.root / "tools" / "alpha" / "show-prs").read_text(encoding="utf-8")
        mutating = (self.root / "tools" / "beta" / "ship").read_text(encoding="utf-8")
        self.assertIn(f"# @tk-verified: {today}", listed)
        self.assertIn(f"# @tk-verified: {today}", shown)
        self.assertIn("# @tk-verified: none", mutating)

        self.assertEqual(
            report["search_misses"],
            [{"query": "deploy status", "count": 2}, {"query": "budget", "count": 1}],
        )
        failing_names = {item["name"] for item in report["failing_tools"]}
        self.assertIn("beta.crash", failing_names)
        self.assertIn("beta.ship", failing_names)
        self.assertIn("beta.ship", report["unused_tools"])
        self.assertIn("beta.crash", report["unused_tools"])
        self.assertNotIn("alpha.list-prs", report["unused_tools"])
        pair_sets = [tuple(pair["tools"]) for pair in report["overlap_candidates"]]
        self.assertIn(("alpha.list-prs", "alpha.show-prs"), pair_sets)

        snapshot = (self.root / "tools" / "beta" / "ship").read_text(encoding="utf-8")
        held = evolve_report(self.root, auto_promote=False)
        self.assertEqual(held["promoted"], [])
        self.assertEqual((self.root / "tools" / "beta" / "ship").read_text(encoding="utf-8"), snapshot)
        self.assertNotIn("alpha.list-prs", held["promoted"])

    def test_evolve_report_empty_state(self) -> None:
        report = evolve_report(self.root)
        self.assertEqual(
            report,
            {
                "promoted": [],
                "search_misses": [],
                "failing_tools": [],
                "unused_tools": [],
                "overlap_candidates": [],
            },
        )


if __name__ == "__main__":
    unittest.main()
