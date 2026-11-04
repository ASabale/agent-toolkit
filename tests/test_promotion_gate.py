"""Live-run gate for evolve_report auto-promotion."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.evolver import evolve_report, log_event, save_tool  # noqa: E402


class PromotionGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._env_patcher = patch.dict(
            os.environ,
            {"TK_NO_TELEMETRY": "", "TK_STATE_DIR": ""},
            clear=False,
        )
        self._env_patcher.start()

    def tearDown(self) -> None:
        self._env_patcher.stop()
        self._tmp.cleanup()

    def _save_unverified_readonly(self, name: str = "lab.echo") -> Path:
        code, out, err = save_tool(
            self.root,
            name,
            "Echo a fixed JSON object",
            from_cmd="printf '%s\\n' '{\"ok\":true}'",
        )
        self.assertEqual(code, 0, err)
        return Path(json.loads(out)["path"])

    def test_no_run_ok_does_not_promote_and_lists_awaiting_live_run(self) -> None:
        path = self._save_unverified_readonly()
        report = evolve_report(self.root, auto_promote=True)
        self.assertEqual(report["promoted"], [])
        self.assertEqual(report["awaiting_live_run"], ["lab.echo"])
        self.assertIn("# @tk-verified: none", path.read_text(encoding="utf-8"))

    def test_run_ok_promotes(self) -> None:
        path = self._save_unverified_readonly()
        log_event(self.root, "run_ok", {"name": "lab.echo"})
        report = evolve_report(self.root, auto_promote=True)
        today = date.today().isoformat()
        self.assertEqual(report["promoted"], ["lab.echo"])
        self.assertEqual(report["awaiting_live_run"], [])
        self.assertIn(f"# @tk-verified: {today}", path.read_text(encoding="utf-8"))

    def test_run_error_only_does_not_promote(self) -> None:
        path = self._save_unverified_readonly()
        log_event(self.root, "run_error", {"name": "lab.echo", "why": "rejected"})
        report = evolve_report(self.root, auto_promote=True)
        self.assertEqual(report["promoted"], [])
        self.assertEqual(report["awaiting_live_run"], ["lab.echo"])
        self.assertIn("# @tk-verified: none", path.read_text(encoding="utf-8"))

    def test_no_promote_includes_awaiting_live_run(self) -> None:
        path = self._save_unverified_readonly()
        report = evolve_report(self.root, auto_promote=False)
        self.assertEqual(report["promoted"], [])
        self.assertEqual(report["awaiting_live_run"], ["lab.echo"])
        self.assertIn("# @tk-verified: none", path.read_text(encoding="utf-8"))
