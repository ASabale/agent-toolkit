"""tk check --verify uses the runner. Evolve still does not stamp writers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.evolver import evolve_report, log_event, save_tool, verify_item  # noqa: E402

TK = ROOT / "tk"


def _run_tk(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["TK_NO_TELEMETRY"] = "1"
    return subprocess.run(
        [str(TK), *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
    )


class VerifyFlagTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._prev = os.environ.get("TK_NO_TELEMETRY")
        os.environ["TK_NO_TELEMETRY"] = ""
        os.environ.pop("TK_STATE_DIR", None)

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("TK_NO_TELEMETRY", None)
        else:
            os.environ["TK_NO_TELEMETRY"] = self._prev
        self._tmp.cleanup()

    def test_cli_verify_requires_exactly_one_name(self) -> None:
        missing = _run_tk("check", "--verify")
        extra = _run_tk("check", "a", "b", "--verify")
        for proc in (missing, extra):
            self.assertEqual(proc.returncode, 2, proc.stderr)
            payload = json.loads(proc.stderr)
            self.assertEqual(payload["fix"], "tk check <name> --verify")
            self.assertIn("error", payload)
            self.assertIn("why", payload)
            self.assertEqual(proc.stdout, "")

    def test_read_only_returns_runner_json_without_stamping(self) -> None:
        code, out, err = save_tool(
            self.root,
            "alpha.look",
            "Look up a record",
            from_cmd="printf '%s\\n' '{\"ok\":true}'",
        )
        self.assertEqual(code, 0, err)
        path = self.root / "tools" / "alpha" / "look"
        before = path.read_text(encoding="utf-8")
        status, payload = verify_item(self.root, "alpha.look")
        self.assertEqual(status, 0, payload)
        self.assertIs(payload["ok"], True)
        self.assertNotIn("verified", payload)
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_mutating_returns_dry_run_plan_without_stamping(self) -> None:
        code, _, err = save_tool(
            self.root,
            "alpha.ship",
            "Ship a branch",
            safety="mutating",
            from_cmd="printf '%s\\n' '{\"ok\":true}'",
        )
        self.assertEqual(code, 0, err)
        path = self.root / "tools" / "alpha" / "ship"
        before = path.read_text(encoding="utf-8")
        status, payload = verify_item(self.root, "alpha.ship")
        self.assertEqual(status, 0, payload)
        self.assertIs(payload["dry_run"], True)
        self.assertTrue(payload["plan"])
        self.assertIn("# @tk-verified: none", path.read_text(encoding="utf-8"))
        self.assertEqual(path.read_text(encoding="utf-8"), before)
        events = self.root / "state" / "events.jsonl"
        if events.is_file():
            self.assertNotIn("tool_verified", events.read_text(encoding="utf-8"))

    def test_destructive_returns_dry_run_plan_and_does_not_write(self) -> None:
        code, _, err = save_tool(
            self.root,
            "alpha.drop",
            "Drop a branch",
            safety="destructive",
            from_cmd="printf '%s\\n' '{\"ok\":true}'",
        )
        self.assertEqual(code, 0, err)
        path = self.root / "tools" / "alpha" / "drop"
        before = path.read_bytes()
        status, payload = verify_item(self.root, "alpha.drop")
        self.assertEqual(status, 0, payload)
        self.assertIs(payload["dry_run"], True)
        self.assertTrue(payload["plan"])
        self.assertEqual(path.read_bytes(), before)

    def test_check_failure_is_not_a_stamp(self) -> None:
        status, payload = verify_item(self.root, "missing.tool")
        self.assertEqual(status, 1)
        self.assertEqual(payload["error"], "check_failed")
        self.assertTrue(payload["why"])
        self.assertEqual(payload["fix"], "tk check missing.tool")

    def test_evolve_does_not_stamp_mutating_or_destructive(self) -> None:
        for name, safety in (("alpha.ship", "mutating"), ("alpha.drop", "destructive")):
            code, _, err = save_tool(
                self.root,
                name,
                f"{safety} tool stays unverified",
                safety=safety,
                from_cmd="printf '%s\\n' '{\"ok\":true}'",
            )
            self.assertEqual(code, 0, err)
            log_event(self.root, "run_ok", {"name": name})
        report = evolve_report(self.root, auto_promote=True)
        self.assertNotIn("alpha.ship", report["promoted"])
        self.assertNotIn("alpha.drop", report["promoted"])
        for leaf in ("ship", "drop"):
            text = (self.root / "tools" / "alpha" / leaf).read_text(encoding="utf-8")
            self.assertIn("# @tk-verified: none", text)
            self.assertNotIn(date.today().isoformat(), text)


if __name__ == "__main__":
    unittest.main()
