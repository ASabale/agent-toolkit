"""Policy decides allow, confirm, or deny. The hash is not a person's identity."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from lib.evolver import write_state_json
from lib.runner import _sha256_file, run_chain, run_tool

_READ = """#!/bin/sh
# @tk-safety: read-only
printf '%s\\n' '{}'
"""

_WRITE = """#!/bin/sh
# @tk-safety: mutating
if [ "${TK_DRY_RUN:-0}" = 1 ]; then
  printf '%s\\n' '{"dry_run":true,"plan":["touch"]}'
  exit 0
fi
touch "$1"
printf '%s\\n' '{}'
"""


def _tool(path: Path, safety: str, *, draft: bool = False) -> dict:
    return {
        "kind": "tool",
        "name": "lab.policy",
        "summary": "policy fixture",
        "safety": safety,
        "args": [],
        "output": "json",
        "example": "tk run lab.policy",
        "verified": "none",
        "path": str(path),
        "draft": draft,
    }


class PolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._telemetry = os.environ.get("TK_NO_TELEMETRY")
        self._state = os.environ.get("TK_STATE_DIR")
        self.state = tempfile.mkdtemp()
        os.environ["TK_NO_TELEMETRY"] = "1"
        os.environ["TK_STATE_DIR"] = self.state
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.tool = self.root / "tool.sh"
        self.tool.write_text(_WRITE, encoding="utf-8")
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

    def _write_policy(self, rules: list[dict]) -> None:
        write_state_json(
            self.root,
            "policy.json",
            {"version": 1, "classes": {"read-only": "allow", "mutating": "confirm", "destructive": "deny"}, "rules": rules},
        )

    def test_missing_policy_uses_defaults_and_omitted_confirm_does_not_write(self) -> None:
        target = self.root / "sentinel"
        script = self.tool.read_text(encoding="utf-8").replace('touch "$1"', f'touch "{target}"')
        self.tool.write_text(script, encoding="utf-8")
        self.tool.chmod(self.tool.stat().st_mode | stat.S_IXUSR)
        code, out, err = run_tool(self.root, _tool(self.tool, "mutating"), {})
        self.assertEqual(code, 0, err)
        self.assertFalse(target.exists())
        payload = json.loads(out)
        self.assertIs(payload["dry_run"], True)
        saved = json.loads((Path(self.state) / "policy.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["classes"]["destructive"], "deny")
        self.assertEqual(saved["classes"]["mutating"], "confirm")
        self.assertEqual(saved["classes"]["read-only"], "allow")

    def test_hash_allow_runs_without_confirm(self) -> None:
        target = self.root / "sentinel"
        self.tool.write_text(_WRITE.replace('touch "$1"', f'touch "{target}"'), encoding="utf-8")
        self.tool.chmod(self.tool.stat().st_mode | stat.S_IXUSR)
        self._write_policy(
            [{"rank": "hash", "sha256": _sha256_file(self.tool), "decision": "allow"}]
        )
        code, out, err = run_tool(self.root, _tool(self.tool, "mutating"), {})
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), {})
        self.assertTrue(target.is_file())

    def test_hash_confirm_without_confirm_does_not_run(self) -> None:
        target = self.root / "sentinel"
        self.tool.write_text(_WRITE.replace('touch "$1"', f'touch "{target}"'), encoding="utf-8")
        self.tool.chmod(self.tool.stat().st_mode | stat.S_IXUSR)
        self._write_policy(
            [{"rank": "hash", "sha256": _sha256_file(self.tool), "decision": "confirm"}]
        )
        code, _out, err = run_tool(self.root, _tool(self.tool, "mutating"), {})
        self.assertEqual(code, 0, err)
        self.assertFalse(target.exists())

    def test_destructive_without_yes_does_not_write_and_yes_warns(self) -> None:
        target = self.root / "sentinel"
        self.tool.write_text(_WRITE.replace('touch "$1"', f'touch "{target}"'), encoding="utf-8")
        self.tool.chmod(self.tool.stat().st_mode | stat.S_IXUSR)
        item = _tool(self.tool, "destructive")
        code, out, err = run_tool(self.root, item, {})
        self.assertEqual(code, 2, err)
        self.assertEqual(out, "")
        self.assertEqual(json.loads(err)["error"], "policy_denied")
        self.assertFalse(target.exists())
        code, out, err = run_tool(self.root, item, {}, confirmed=True)
        self.assertEqual(code, 0, err)
        self.assertTrue(target.is_file())
        self.assertIn("deprecated", err)
        audit = (Path(self.state) / "audit.jsonl").read_text(encoding="utf-8")
        self.assertIn('"via":"yes"', audit)

    def test_name_allow_does_not_survive_a_byte_change(self) -> None:
        target = self.root / "sentinel"
        self.tool.write_text(_WRITE.replace('touch "$1"', f'touch "{target}"'), encoding="utf-8")
        self.tool.chmod(self.tool.stat().st_mode | stat.S_IXUSR)
        old = _sha256_file(self.tool)
        self._write_policy([{"rank": "name", "name": "lab.policy", "decision": "allow"}])
        self.tool.write_text(self.tool.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        self.tool.chmod(self.tool.stat().st_mode | stat.S_IXUSR)
        self.assertNotEqual(_sha256_file(self.tool), old)
        code, _out, err = run_tool(self.root, _tool(self.tool, "mutating"), {})
        self.assertEqual(code, 0, err)
        self.assertFalse(target.exists())

    def test_old_hash_does_not_authorize_new_bytes(self) -> None:
        target = self.root / "sentinel"
        self.tool.write_text(_WRITE.replace('touch "$1"', f'touch "{target}"'), encoding="utf-8")
        self.tool.chmod(self.tool.stat().st_mode | stat.S_IXUSR)
        self._write_policy([{"rank": "hash", "sha256": _sha256_file(self.tool), "decision": "allow"}])
        self.tool.write_text(self.tool.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        self.tool.chmod(self.tool.stat().st_mode | stat.S_IXUSR)
        code, _out, err = run_tool(self.root, _tool(self.tool, "mutating"), {})
        self.assertEqual(code, 0, err)
        self.assertFalse(target.exists())

    def test_conflict_and_invalid_policy_do_not_run(self) -> None:
        target = self.root / "sentinel"
        self.tool.write_text(_WRITE.replace('touch "$1"', f'touch "{target}"'), encoding="utf-8")
        digest = _sha256_file(self.tool)
        self._write_policy(
            [
                {"rank": "hash", "sha256": digest, "decision": "allow"},
                {"rank": "hash", "sha256": digest, "decision": "deny"},
            ]
        )
        code, out, err = run_tool(self.root, _tool(self.tool, "mutating"), {})
        self.assertEqual(code, 1, err)
        self.assertEqual(json.loads(err)["error"], "policy_conflict")
        self.assertFalse(target.exists())
        (Path(self.state) / "policy.json").write_text("{", encoding="utf-8")
        code, out, err = run_tool(self.root, _tool(self.tool, "mutating"), {})
        self.assertEqual(code, 1, err)
        self.assertEqual(json.loads(err)["error"], "invalid_policy")
        self.assertEqual(out, "")
        self.assertFalse(target.exists())
        reader = self.root / "read.sh"
        reader.write_text(_READ, encoding="utf-8")
        reader.chmod(reader.stat().st_mode | stat.S_IXUSR)
        code, _out, err = run_tool(self.root, _tool(reader, "read-only", draft=True), {})
        self.assertEqual(code, 1, err)
        self.assertEqual(json.loads(err)["error"], "invalid_policy")

    def test_draft_read_only_without_a_hash_does_not_run(self) -> None:
        reader = self.root / "read.sh"
        reader.write_text(_READ, encoding="utf-8")
        reader.chmod(reader.stat().st_mode | stat.S_IXUSR)
        code, out, err = run_tool(self.root, _tool(reader, "read-only", draft=True), {})
        self.assertEqual(code, 2, err)
        self.assertEqual(out, "")
        self.assertEqual(json.loads(err)["error"], "policy_denied")

    def test_catalog_read_only_still_runs(self) -> None:
        reader = self.root / "read.sh"
        reader.write_text(_READ, encoding="utf-8")
        reader.chmod(reader.stat().st_mode | stat.S_IXUSR)
        code, out, err = run_tool(self.root, _tool(reader, "read-only"), {})
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), {})

    def test_chain_denied_writer_does_not_start(self) -> None:
        marker = self.root / "step1"
        first = self.root / "first.sh"
        first.write_text(_READ.replace("{}", f'{{"ok":true}}') , encoding="utf-8")
        # keep a side effect so we can see step 1 did not run
        first.write_text(
            f"#!/bin/sh\ntouch {marker}\nprintf '%s\\n' '{{}}'\n",
            encoding="utf-8",
        )
        first.chmod(first.stat().st_mode | stat.S_IXUSR)
        second = self.root / "second.sh"
        second.write_text("#!/bin/sh\nprintf '%s\\n' '{}'\n", encoding="utf-8")
        second.chmod(second.stat().st_mode | stat.S_IXUSR)
        catalog = {
            "lab.first": _tool(first, "read-only") | {"name": "lab.first"},
            "lab.second": _tool(second, "destructive") | {"name": "lab.second"},
        }
        chain = {
            "kind": "chain",
            "name": "lab.chain",
            "safety": "read-only",
            "example": "tk run lab.chain",
            "args": [],
            "steps": [{"tool": "lab.first", "args": {}}, {"tool": "lab.second", "args": {}}],
        }
        from unittest.mock import patch

        with patch("lib.catalog.discover_catalog", return_value=catalog):
            code, out, err = run_chain(self.root, chain, {})
        self.assertEqual(code, 2, err)
        self.assertEqual(out, "")
        self.assertEqual(json.loads(err)["error"], "policy_denied")
        self.assertFalse(marker.exists())
