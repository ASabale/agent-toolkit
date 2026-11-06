"""plan_id binds a later --confirm to the dry-run plan. --yes still executes."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.catalog import _header_errors  # noqa: E402
from lib.runner import confirm_id_from_argv, parse_cli_flags, run_tool  # noqa: E402

_SCRIPT = """#!/usr/bin/env bash
# @tk-name: lab.planid
# @tk-summary: Touch a path for plan id tests
# @tk-safety: mutating
# @tk-arg: --path | required | string | Path to touch
# @tk-output: json | object
# @tk-example: tk run lab.planid --path example
# @tk-verified: none
if [ "${TK_DRY_RUN:-0}" = 1 ]; then
  printf '%s\\n' '{"dry_run":true,"plan":["touch"]}'
  exit 0
fi
touch "$TK_ARG_PATH"
printf '%s\\n' '{}'
"""


def _item(path: Path) -> dict:
    return {
        "kind": "tool",
        "name": "lab.planid",
        "summary": "Touch a path",
        "safety": "mutating",
        "args": [
            {
                "flag": "--path",
                "env_var": "TK_ARG_PATH",
                "required": True,
                "type": "string",
                "description": "Path to touch",
            }
        ],
        "output": "json",
        "example": "tk run lab.planid --path example",
        "verified": "none",
        "path": str(path),
    }


class PlanIdTests(unittest.TestCase):
    def setUp(self) -> None:
        self._telemetry = os.environ.get("TK_NO_TELEMETRY")
        self._state = os.environ.get("TK_STATE_DIR")
        self.state = tempfile.mkdtemp()
        os.environ["TK_NO_TELEMETRY"] = "1"
        os.environ["TK_STATE_DIR"] = self.state
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.tool = self.root / "tools" / "lab" / "planid"
        self.tool.parent.mkdir(parents=True)
        self.tool.write_text(_SCRIPT, encoding="utf-8")
        self.tool.chmod(self.tool.stat().st_mode | stat.S_IXUSR)

    def tearDown(self) -> None:
        self.tmp.cleanup()
        if self._telemetry is None:
            os.environ.pop("TK_NO_TELEMETRY", None)
        else:
            os.environ["TK_NO_TELEMETRY"] = self._telemetry
        if self._state is None:
            os.environ.pop("TK_STATE_DIR", None)
        else:
            os.environ["TK_STATE_DIR"] = self._state

    def _unconfirmed(self, target: Path) -> dict:
        code, out, err = run_tool(
            self.root, _item(self.tool), {"--path": str(target)}, confirmed=False
        )
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def test_a_changed_flag_changes_plan_id_and_apply_still_ends_with_yes(self) -> None:
        first = self._unconfirmed(self.root / "a")
        second = self._unconfirmed(self.root / "b")
        self.assertNotEqual(first["plan_id"], second["plan_id"])
        self.assertEqual(len(first["plan_id"]), 8)
        for payload in (first, second):
            self.assertIs(payload["dry_run"], True)
            self.assertEqual(payload["plan"], ["touch"])
            self.assertTrue(payload["apply"].endswith("--yes"))
            self.assertIn("--confirm " + payload["plan_id"], payload["confirm"])
            self.assertNotIn("--yes", payload["confirm"])

    def test_stale_confirm_is_refused_and_does_not_write(self) -> None:
        first = self._unconfirmed(self.root / "a")
        target = self.root / "b"
        code, out, err = run_tool(
            self.root,
            _item(self.tool),
            {"--path": str(target)},
            confirmed=False,
            confirm_id=first["plan_id"],
        )
        self.assertEqual(code, 2, err)
        self.assertEqual(out, "")
        payload = json.loads(err)
        self.assertEqual(payload["error"], "plan_mismatch")
        self.assertIn(first["plan_id"], payload["why"])
        self.assertIn("plan_id is ", payload["why"])
        self.assertNotIn("authorized", payload["why"])
        self.assertNotIn("--confirm", payload["fix"])
        self.assertNotIn("--yes", payload["fix"])
        self.assertFalse(target.exists())

    def test_matching_confirm_via_tk_executes(self) -> None:
        catalog_tool = ROOT / "tools" / "lab" / "planid"
        created_lab = not catalog_tool.parent.exists()
        catalog_tool.parent.mkdir(parents=True, exist_ok=True)
        catalog_tool.write_text(_SCRIPT, encoding="utf-8")
        catalog_tool.chmod(catalog_tool.stat().st_mode | stat.S_IXUSR)
        target = self.root / "touched"
        env = os.environ.copy()
        env["TK_NO_TELEMETRY"] = "1"
        env["TK_STATE_DIR"] = self.state
        try:
            preview = subprocess.run(
                [sys.executable, str(ROOT / "tk"), "run", "lab.planid", "--path", str(target)],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(preview.returncode, 0, preview.stderr)
            plan_id = json.loads(preview.stdout)["plan_id"]
            self.assertFalse(target.exists())
            ran = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tk"),
                    "run",
                    "lab.planid",
                    "--path",
                    str(target),
                    "--confirm",
                    plan_id,
                ],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(ran.returncode, 0, ran.stderr)
            self.assertEqual(json.loads(ran.stdout), {})
            self.assertTrue(target.is_file())
        finally:
            catalog_tool.unlink(missing_ok=True)
            if created_lab:
                catalog_tool.parent.rmdir()

    def test_yes_still_executes_and_apply_ends_with_yes(self) -> None:
        target = self.root / "touched"
        preview = self._unconfirmed(target)
        self.assertTrue(preview["apply"].endswith("--yes"))
        self.assertFalse(target.exists())
        code, out, err = run_tool(
            self.root, _item(self.tool), {"--path": str(target)}, confirmed=True
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), {})
        self.assertTrue(target.is_file())

    def test_parse_does_not_keep_confirm_as_a_tool_flag(self) -> None:
        item = {"args": [{"flag": "--path", "type": "string"}]}
        flags, dry_run, positional = parse_cli_flags(
            ["--path", "x", "--confirm", "ab12cd34"], item
        )
        self.assertEqual(flags, {"--path": "x"})
        self.assertFalse(dry_run)
        self.assertEqual(positional, [])
        self.assertEqual(
            confirm_id_from_argv(["--path", "x", "--confirm", "ab12cd34"]),
            "ab12cd34",
        )
        self.assertEqual(confirm_id_from_argv(["--confirm"]), "")
        self.assertIsNone(confirm_id_from_argv(["--path", "x"]))

    def test_header_rejects_confirm_flag(self) -> None:
        errors = _header_errors(
            {
                "name": "demo.confirm",
                "summary": "Declares the reserved flag",
                "safety": "read-only",
                "output": "json",
                "example": "tk run demo.confirm",
                "verified": "none",
                "args": [{"flag": "--confirm", "type": "string"}],
            }
        )
        self.assertTrue(any("reserved flag: --confirm" in error for error in errors))

    def test_empty_confirm_does_not_write(self) -> None:
        target = self.root / "touched"
        code, out, err = run_tool(
            self.root,
            _item(self.tool),
            {"--path": str(target)},
            confirmed=False,
            confirm_id="",
        )
        self.assertEqual(code, 2, err)
        self.assertEqual(out, "")
        payload = json.loads(err)
        self.assertEqual(payload["error"], "plan_mismatch")
        self.assertEqual(payload["why"], "--confirm needs a plan_id")
        self.assertNotIn("authorized", payload["why"])
        self.assertFalse(target.exists())
