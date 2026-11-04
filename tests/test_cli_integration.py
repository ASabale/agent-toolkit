"""End-to-end tests for the ./tk binary in an isolated toolkit copy."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.evolver import MIN_UNUSED_RUN_EVENTS  # noqa: E402


class CliIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "toolkit"
        shutil.copytree(
            ROOT,
            self.root,
            ignore=shutil.ignore_patterns(
                "__pycache__",
                "*.pyc",
                ".git",
                "state",
                ".code-review-graph",
            ),
        )
        self.tk = self.root / "tk"
        self.tk.chmod(self.tk.stat().st_mode | 0o755)
        self._base_env = os.environ.copy()
        self._base_env["TK_NO_TELEMETRY"] = ""
        self._base_env["TK_STATE_DIR"] = ""

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, *args: str, stdin: str | None = None, env: dict | None = None) -> subprocess.CompletedProcess[str]:
        run_env = env if env is not None else self._base_env
        return subprocess.run(
            [str(self.tk), *args],
            input=stdin,
            capture_output=True,
            text=True,
            cwd=self.root,
            env=run_env,
        )

    def _events(self) -> list[dict]:
        path = self.root / "state" / "events.jsonl"
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _seed_run_events(self, count: int, name: str = "lab.keep") -> None:
        path = self.root / "state" / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat()
        with path.open("a", encoding="utf-8") as handle:
            for _ in range(count):
                handle.write(
                    json.dumps({"ts": ts, "event": "run_ok", "name": name}, separators=(",", ":"))
                    + "\n"
                )

    def _assert_insufficient_telemetry(self, proc: subprocess.CompletedProcess[str], run_events: int = 0) -> None:
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout.strip(), "")
        payload = json.loads(proc.stderr)
        self.assertEqual(payload["error"], "insufficient_telemetry")
        self.assertEqual(payload["why"], f"{run_events} run events < {MIN_UNUSED_RUN_EVENTS}")
        self.assertEqual(payload["fix"], "tk prune <name> --dry-run")

    def test_find_logs_misses_and_not_hits(self) -> None:
        hit = self._run("find", "json.pick")
        self.assertEqual(hit.returncode, 0, hit.stderr)
        self.assertIn("json.pick", hit.stdout)
        self.assertIn("tk run json.pick", hit.stdout)
        self.assertFalse(any(event["event"] == "search_miss" for event in self._events()))

        miss = self._run("find", "no-such-widget")
        self.assertEqual(miss.returncode, 0, miss.stderr)
        self.assertEqual(miss.stdout.strip(), "")
        misses = [event for event in self._events() if event["event"] == "search_miss"]
        self.assertEqual(len(misses), 1)
        self.assertEqual(misses[0]["query"], "no-such-widget")

    def test_find_limit_slices_and_rejects_bad_flags(self) -> None:
        limited = self._run("find", "--limit", "2")
        self.assertEqual(limited.returncode, 0, limited.stderr)
        names = [line.split(" ", 1)[0] for line in limited.stdout.splitlines() if line and not line.startswith(" ")]
        self.assertEqual(len(names), 2)

        equals = self._run("find", "json", "--limit=1")
        self.assertEqual(equals.returncode, 0, equals.stderr)
        equals_names = [line.split(" ", 1)[0] for line in equals.stdout.splitlines() if line and not line.startswith(" ")]
        self.assertEqual(len(equals_names), 1)
        self.assertIn("json", equals_names[0])

        bad = self._run("find", "--limit", "0")
        self.assertEqual(bad.returncode, 2)
        self.assertEqual(json.loads(bad.stderr)["error"], "invalid_type")

        unknown = self._run("find", "--json")
        self.assertEqual(unknown.returncode, 2)
        self.assertEqual(json.loads(unknown.stderr)["error"], "unknown_flag")

    def test_find_namespace_filters_and_rejects_empty(self) -> None:
        limited = self._run("find", "--namespace", "git", "--limit", "2")
        self.assertEqual(limited.returncode, 0, limited.stderr)
        names = [line.split(" ", 1)[0] for line in limited.stdout.splitlines() if line and not line.startswith(" ")]
        self.assertEqual(names, ["git.blame-slice", "git.branch-digest"])

        equals = self._run("find", "--namespace=git", "--limit", "1")
        self.assertEqual(equals.returncode, 0, equals.stderr)
        equals_names = [line.split(" ", 1)[0] for line in equals.stdout.splitlines() if line and not line.startswith(" ")]
        self.assertEqual(equals_names, ["git.blame-slice"])

        empty = self._run("find", "--namespace=")
        self.assertEqual(empty.returncode, 2)
        self.assertEqual(json.loads(empty.stderr)["error"], "missing_flag")

        missing = self._run("find", "--namespace")
        self.assertEqual(missing.returncode, 2)
        self.assertEqual(json.loads(missing.stderr)["error"], "missing_flag")

    def test_find_unknown_namespace_logs_namespace_search_miss(self) -> None:
        miss = self._run("find", "--namespace", "unknown")
        self.assertEqual(miss.returncode, 0, miss.stderr)
        self.assertEqual(miss.stdout.strip(), "")
        misses = [event for event in self._events() if event["event"] == "search_miss"]
        self.assertEqual(len(misses), 1)
        self.assertEqual(misses[0]["query"], "namespace:unknown")

    def test_check_multiple_names_aggregates(self) -> None:
        checked = self._run("check", "json.pick", "json.query")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        payload = json.loads(checked.stdout)
        self.assertEqual(payload["checked"], 2)
        self.assertTrue(payload["ok"])
        self.assertEqual([item["name"] for item in payload["results"]], ["json.pick", "json.query"])
        self.assertEqual(payload["errors"], [])

        missing = self._run("check", "json.pick", "no.such.tool")
        self.assertEqual(missing.returncode, 1)
        failed = json.loads(missing.stdout)
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["checked"], 2)
        self.assertTrue(any(err.startswith("no.such.tool:") for err in failed["errors"]))

    def test_info_and_run_suggest_closest_item(self) -> None:
        info = self._run("info", "json.pik")
        self.assertEqual(info.returncode, 2)
        payload = json.loads(info.stderr)
        self.assertEqual(payload["error"], "not_found")
        self.assertIn("(did you mean json.pick?)", payload["why"])
        self.assertIn("json.pick", payload["fix"])

        unknown = self._run("run", "zzzzqqqq")
        self.assertEqual(unknown.returncode, 2)
        payload = json.loads(unknown.stderr)
        self.assertNotIn("did you mean", payload["why"])
        self.assertEqual(payload["fix"], "tk find")

        typo = self._run("run", "json.pik")
        self.assertEqual(typo.returncode, 2)
        payload = json.loads(typo.stderr)
        self.assertIn("(did you mean json.pick?)", payload["why"])
        self.assertIn("tk run json.pick", payload["fix"])

    def test_no_telemetry_skips_events_file(self) -> None:
        env = os.environ.copy()
        env["TK_NO_TELEMETRY"] = "1"
        miss = self._run("info", "zzzzqqqq", env=env)
        self.assertEqual(miss.returncode, 2)
        self.assertFalse((self.root / "state" / "events.jsonl").exists())

    def test_run_valid_tool_missing_flag_fix_and_positional_rejection(self) -> None:
        missing = self._run("run", "json.pick")
        self.assertEqual(missing.returncode, 1, missing.stderr)
        self.assertEqual(missing.stdout.strip(), "")
        payload = json.loads(missing.stderr)
        self.assertEqual(payload["error"], "missing_required")
        self.assertIn("--keys", payload["fix"])
        self.assertIn("<value>", payload["fix"])

        fix = payload["fix"].replace("<value>", "branch")
        self.assertTrue(fix.startswith("tk run "))
        ran = self._run(*fix.split()[1:], stdin='{"branch":"main","extra":1}\n')
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertEqual(json.loads(ran.stdout), {"branch": "main"})

        positional = self._run("run", "json.pick", "extra", "--keys", "branch", stdin='{"branch":"main"}\n')
        self.assertEqual(positional.returncode, 1)
        rejected = json.loads(positional.stderr)
        self.assertEqual(rejected["error"], "positional_arguments_forbidden")

    def test_save_keeps_valid_tool_and_quarantines_broken_tool(self) -> None:
        created = self._run(
            "save",
            "lab.echo",
            "--summary",
            "Echo a fixed JSON object",
            "--from-cmd",
            "printf '%s\\n' '{\"ok\":true}'",
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        body = json.loads(created.stdout)
        self.assertTrue(body["ok"])
        self.assertEqual(body["name"], "lab.echo")
        tool = self.root / "tools" / "lab" / "echo"
        self.assertTrue(tool.is_file())
        self.assertTrue(tool.stat().st_mode & 0o111)

        draft = self.root / "broken.sh"
        draft.write_text(
            "#!/usr/bin/env bash\n"
            "# @tk-name: lab.bad\n"
            "# @tk-summary: Prints plain text\n"
            "# @tk-safety: read-only\n"
            "# @tk-output: json | Compact JSON result\n"
            "# @tk-example: tk run lab.bad\n"
            "# @tk-verified: none\n"
            "printf 'nope\\n'\n",
            encoding="utf-8",
        )
        broken = self._run(
            "save",
            "lab.bad",
            "--summary",
            "Prints plain text",
            "--file",
            str(draft),
        )
        self.assertNotEqual(broken.returncode, 0)
        err = json.loads(broken.stderr)
        self.assertEqual(err["error"], "check_failed")
        self.assertFalse((self.root / "tools" / "lab" / "bad").exists())
        quarantine = self.root / "state" / "quarantine"
        drafts = list(quarantine.glob("*")) if quarantine.is_dir() else []
        self.assertTrue(drafts)
        self.assertTrue(any("nope" in draft.read_text(encoding="utf-8") for draft in drafts))

    def test_chain_save_and_run(self) -> None:
        saved = self._run(
            "save",
            "lab.echo",
            "--summary",
            "Echo a fixed JSON object",
            "--from-cmd",
            "printf '%s\\n' '{\"ok\":true}'",
        )
        self.assertEqual(saved.returncode, 0, saved.stderr)
        chained = self._run(
            "chain",
            "save",
            "lab.pipe",
            "--summary",
            "Echo via a chain",
            "--steps",
            '[{"tool":"lab.echo"}]',
        )
        self.assertEqual(chained.returncode, 0, chained.stderr)
        self.assertTrue(json.loads(chained.stdout)["ok"])
        self.assertTrue((self.root / "chains" / "lab.pipe.json").is_file())

        ran = self._run("run", "lab.pipe")
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertEqual(json.loads(ran.stdout), {"ok": True})

    def test_chain_save_arg_force_and_plain_check_json(self) -> None:
        saved = self._run(
            "save",
            "lab.echo",
            "--summary",
            "Echo a fixed JSON object",
            "--from-cmd",
            "printf '%s\\n' '{\"ok\":true}'",
        )
        self.assertEqual(saved.returncode, 0, saved.stderr)
        chained = self._run(
            "chain",
            "save",
            "lab.pipe",
            "--summary",
            "Echo via a chain",
            "--steps",
            "lab.echo",
            "--arg",
            "--token | required | string | Token to pass",
            "--example",
            "tk run lab.pipe --token example",
        )
        self.assertEqual(chained.returncode, 0, chained.stderr)
        document = json.loads((self.root / "chains" / "lab.pipe.json").read_text(encoding="utf-8"))
        self.assertEqual(document["args"][0]["flag"], "--token")
        self.assertEqual(document["example"], "tk run lab.pipe --token example")

        refused = self._run(
            "chain",
            "save",
            "lab.pipe",
            "--summary",
            "Echo via a chain again",
            "--steps",
            "lab.echo",
        )
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(json.loads(refused.stderr)["error"], "already_exists")

        forced = self._run(
            "chain",
            "save",
            "lab.pipe",
            "--summary",
            "Echo via a replaced chain",
            "--steps",
            "lab.echo",
            "--force",
        )
        self.assertEqual(forced.returncode, 0, forced.stderr)
        replaced = json.loads((self.root / "chains" / "lab.pipe.json").read_text(encoding="utf-8"))
        self.assertEqual(replaced["summary"], "Echo via a replaced chain")

        checked = self._run("check")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        payload = json.loads(checked.stdout)
        self.assertIn("checked", payload)
        self.assertTrue(payload["ok"])

    def test_check_json(self) -> None:
        checked = self._run("check", "--json")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        payload = json.loads(checked.stdout)
        self.assertTrue(payload["ok"])
        self.assertGreaterEqual(payload["checked"], 1)
        self.assertIsInstance(payload["results"], list)
        self.assertEqual(payload["errors"], [])

    def test_evolve_uses_runs_misses_and_promotes_read_only_tools(self) -> None:
        saved = self._run(
            "save",
            "lab.echo",
            "--summary",
            "Echo a fixed JSON object",
            "--from-cmd",
            "printf '%s\\n' '{\"ok\":true}'",
        )
        self.assertEqual(saved.returncode, 0, saved.stderr)
        missed = self._run("find", "deploy-status-missing")
        self.assertEqual(missed.returncode, 0, missed.stderr)

        before = self._run("evolve")
        self.assertEqual(before.returncode, 0, before.stderr)
        report = json.loads(before.stdout)
        self.assertEqual(report["unused_tools"], [])
        self.assertEqual(report["unused_reason"], "insufficient_telemetry")
        self.assertEqual(report["telemetry"]["run_events"], 0)
        self.assertIn("lab.echo", report["promoted"])
        self.assertIn(
            {"query": "deploy-status-missing", "count": 1},
            report["search_misses"],
        )
        today = date.today().isoformat()
        text = (self.root / "tools" / "lab" / "echo").read_text(encoding="utf-8")
        self.assertIn(f"# @tk-verified: {today}", text)

        ran = self._run("run", "lab.echo")
        self.assertEqual(ran.returncode, 0, ran.stderr)
        after = json.loads(self._run("evolve").stdout)
        self.assertNotIn("lab.echo", after["unused_tools"])
        self.assertEqual(after["unused_reason"], "insufficient_telemetry")
        self.assertEqual(after["telemetry"]["run_events"], 1)
        self.assertIn(
            {"query": "deploy-status-missing", "count": 1},
            after["search_misses"],
        )
        self.assertNotIn("lab.echo", after["promoted"])

    def test_prune_unused_dry_run_keeps_chain_dependencies(self) -> None:
        saved = self._run(
            "save",
            "lab.echo",
            "--summary",
            "Echo a fixed JSON object",
            "--from-cmd",
            "printf '%s\\n' '{\"ok\":true}'",
        )
        self.assertEqual(saved.returncode, 0, saved.stderr)
        kept = self._run(
            "save",
            "lab.keep",
            "--summary",
            "Echo a kept JSON object",
            "--from-cmd",
            "printf '%s\\n' '{\"ok\":true}'",
        )
        self.assertEqual(kept.returncode, 0, kept.stderr)
        chained = self._run(
            "chain",
            "save",
            "lab.pipe",
            "--summary",
            "Keep echo behind a used chain",
            "--steps",
            '[{"tool":"lab.keep"}]',
        )
        self.assertEqual(chained.returncode, 0, chained.stderr)
        ran = self._run("run", "lab.pipe")
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self._seed_run_events(MIN_UNUSED_RUN_EVENTS - 1, "lab.pipe")

        preview = self._run("prune", "--unused", "--dry-run")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        payload = json.loads(preview.stdout)
        self.assertTrue(payload["dry_run"])
        self.assertIn("lab.echo", payload["pruned"])
        self.assertNotIn("lab.keep", payload["pruned"])
        self.assertNotIn("lab.pipe", payload["pruned"])
        self.assertTrue((self.root / "tools" / "lab" / "echo").is_file())
        self.assertTrue((self.root / "tools" / "lab" / "keep").is_file())
        self.assertTrue((self.root / "chains" / "lab.pipe.json").is_file())

    def test_prune_unused_refuses_cold_start_and_archives_nothing(self) -> None:
        echo = self.root / "tools" / "json" / "pick"
        chain = self.root / "chains" / "gh.triage-pr.json"
        self.assertTrue(echo.is_file())
        self.assertTrue(chain.is_file())

        preview = self._run("prune", "--unused", "--dry-run")
        self._assert_insufficient_telemetry(preview)
        self.assertFalse((self.root / "state" / "archive").exists())
        self.assertTrue(echo.is_file())
        self.assertTrue(chain.is_file())

        real = self._run("prune", "--unused")
        self._assert_insufficient_telemetry(real)
        self.assertFalse((self.root / "state" / "archive").exists())
        self.assertTrue(echo.is_file())
        self.assertTrue(chain.is_file())

        named = self._run(
            "save",
            "lab.echo",
            "--summary",
            "Echo a fixed JSON object",
            "--from-cmd",
            "printf '%s\\n' '{\"ok\":true}'",
        )
        self.assertEqual(named.returncode, 0, named.stderr)
        explicit = self._run("prune", "lab.echo", "--dry-run")
        self.assertEqual(explicit.returncode, 0, explicit.stderr)
        payload = json.loads(explicit.stdout)
        self.assertEqual(payload["pruned"], ["lab.echo"])
        self.assertTrue((self.root / "tools" / "lab" / "echo").is_file())

        archived = self._run("prune", "lab.echo")
        self.assertEqual(archived.returncode, 0, archived.stderr)
        self.assertFalse((self.root / "tools" / "lab" / "echo").exists())

        below = self._run("prune", "--unused", "--dry-run")
        # lab.echo prune may have logged tool_pruned; still no run_ok/run_error.
        self._assert_insufficient_telemetry(below, 0)
        self._seed_run_events(MIN_UNUSED_RUN_EVENTS - 1, "json.pick")
        almost = self._run("prune", "--unused")
        self._assert_insufficient_telemetry(almost, MIN_UNUSED_RUN_EVENTS - 1)
        self.assertTrue(echo.is_file())
        self.assertTrue(chain.is_file())

    def test_evolve_no_promote_fresh_state_prints_telemetry(self) -> None:
        env = self._base_env.copy()
        env["TK_STATE_DIR"] = str(self.root / "fresh-state")
        evolved = self._run("evolve", "--no-promote", env=env)
        self.assertEqual(evolved.returncode, 0, evolved.stderr)
        report = json.loads(evolved.stdout)
        self.assertEqual(report["unused_tools"], [])
        self.assertEqual(report["unused_reason"], "insufficient_telemetry")
        self.assertEqual(report["telemetry"]["events"], 0)
        self.assertEqual(report["telemetry"]["run_events"], 0)
        self.assertIsNone(report["telemetry"]["first_ts"])


if __name__ == "__main__":
    unittest.main()
