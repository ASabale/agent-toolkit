"""End-to-end tests for the ./tk binary in an isolated toolkit copy."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.tk), *args],
            input=stdin,
            capture_output=True,
            text=True,
            cwd=self.root,
        )

    def _events(self) -> list[dict]:
        path = self.root / "state" / "events.jsonl"
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

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
        self.assertIn("lab.echo", report["unused_tools"])
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


if __name__ == "__main__":
    unittest.main()
