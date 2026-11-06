"""Chain steps pin tool file bytes and stop when those bytes change."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from lib.catalog import check_item, discover_catalog
from lib.evolver import save_chain, save_tool, write_state_json
from lib.runner import _sha256_file, run_chain


class ChainPinTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._previous = os.environ.get("TK_STATE_DIR")
        os.environ["TK_STATE_DIR"] = str(self.root / "state")

    def tearDown(self) -> None:
        if self._previous is None:
            os.environ.pop("TK_STATE_DIR", None)
        else:
            os.environ["TK_STATE_DIR"] = self._previous
        self._tmp.cleanup()

    def _save_tool(self, name: str, body: str) -> Path:
        code, _, err = save_tool(self.root, name, name, from_cmd=body)
        self.assertEqual(code, 0, err)
        return self.root / "tools" / Path(*name.split("."))

    def _allow(self, *names: str) -> None:
        rules = [
            {
                "rank": "hash",
                "sha256": _sha256_file(discover_catalog(self.root)[name]["path"]),
                "decision": "allow",
            }
            for name in names
        ]
        write_state_json(
            self.root,
            "policy.json",
            {
                "version": 1,
                "classes": {
                    "read-only": "allow",
                    "mutating": "confirm",
                    "destructive": "deny",
                },
                "rules": rules,
            },
        )

    def _chain(self, name: str, steps: list[dict]) -> Path:
        code, _, err = save_chain(self.root, name, name, steps=steps)
        self.assertEqual(code, 0, err)
        return self.root / "chains" / f"{name}.json"

    def test_resave_updates_the_pin_and_the_chain_runs(self) -> None:
        sentinel = self.root / "ran"
        self._save_tool("demo.touch", f"touch {sentinel}; printf '%s\\n' '{{}}'")
        path = self._chain("demo.pinned", [{"tool": "demo.touch", "args": {}}])
        saved = json.loads(path.read_text(encoding="utf-8"))
        pin = saved["steps"][0]["tool_sha256"]
        self.assertEqual(len(pin), 64)
        self.assertNotIn(str(self.root), pin)
        tool = self.root / "tools" / "demo" / "touch"
        tool.write_bytes(tool.read_bytes() + b"\n")
        code, _, err = save_chain(
            self.root,
            "demo.pinned",
            "demo.pinned",
            steps=[{"tool": "demo.touch", "args": {}}],
            force=True,
        )
        self.assertEqual(code, 0, err)
        updated = json.loads(path.read_text(encoding="utf-8"))["steps"][0]["tool_sha256"]
        self.assertNotEqual(updated, pin)
        self.assertEqual(updated, hashlib.sha256(tool.read_bytes()).hexdigest())
        self._allow("demo.touch")
        item = discover_catalog(self.root)["demo.pinned"]
        ran, out, err = run_chain(self.root, item, {})
        self.assertEqual(ran, 0, err)
        self.assertEqual(json.loads(out), {})
        self.assertTrue(sentinel.exists())

    def test_same_bytes_under_another_path_run(self) -> None:
        self._save_tool("demo.look", "printf '%s\\n' '{\"ok\":true}'")
        self._chain("demo.copied", [{"tool": "demo.look", "args": {}}])
        other = Path(self._tmp.name) / "other"
        shutil.copytree(self.root / "tools", other / "tools")
        shutil.copytree(self.root / "chains", other / "chains")
        os.environ["TK_STATE_DIR"] = str(other / "state")
        original = discover_catalog(self.root)["demo.look"]["path"]
        copied = discover_catalog(other)["demo.look"]["path"]
        self.assertNotEqual(original, copied)
        item = discover_catalog(other)["demo.copied"]
        code, out, err = run_chain(other, item, {})
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), {"ok": True})

    def test_legacy_chain_runs_and_check_says_unpinned(self) -> None:
        tool = self._save_tool("demo.look", "printf '%s\\n' '{\"ok\":true}'")
        chain = self.root / "chains" / "demo.legacy.json"
        chain.parent.mkdir(parents=True, exist_ok=True)
        chain.write_text(
            json.dumps(
                {
                    "kind": "chain",
                    "name": "demo.legacy",
                    "summary": "legacy",
                    "safety": "read-only",
                    "args": [],
                    "steps": [{"tool": "demo.look", "args": {}}],
                    "output": "json | Chain result",
                    "example": "tk run demo.legacy",
                    "verified": "none",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        checked = check_item(self.root, "demo.legacy")
        self.assertTrue(checked["ok"], checked)
        self.assertIn("unpinned", checked["warnings"])
        self._allow("demo.look")
        item = discover_catalog(self.root)["demo.legacy"]
        code, out, err = run_chain(self.root, item, {})
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), {"ok": True})
        self.assertTrue(tool.is_file())

    def test_changed_pin_does_not_start(self) -> None:
        """Named failure: a pinned tool used to run after its bytes changed."""
        sentinel = self.root / "sentinel"
        tool = self._save_tool("demo.touch", f"touch {sentinel}; printf '%s\\n' '{{}}'")
        path = self._chain("demo.pinned", [{"tool": "demo.touch", "args": {}}])
        before = path.read_bytes()
        tool.write_bytes(tool.read_bytes() + b"x")
        item = discover_catalog(self.root)["demo.pinned"]
        code, _out, err = run_chain(self.root, item, {})
        self.assertEqual(code, 1)
        payload = json.loads(err)
        self.assertEqual(payload["error"], "chain_dependency_changed")
        self.assertIn("step 1", payload["why"])
        self.assertIn("demo.touch", payload["why"])
        self.assertIn("tk chain save", payload["fix"])
        self.assertFalse(sentinel.exists())
        self.assertEqual(path.read_bytes(), before)

    def test_step_one_replacing_step_two_is_partial(self) -> None:
        first = self.root / "first"
        second = self.root / "second"
        step2 = self.root / "tools" / "demo" / "two"
        self._save_tool("demo.one", f"touch {first}; printf 'x' >> {step2}; printf '%s\\n' '{{}}'")
        self._save_tool("demo.two", f"touch {second}; printf '%s\\n' '{{}}'")
        self._chain(
            "demo.swap",
            [{"tool": "demo.one", "args": {}}, {"tool": "demo.two", "args": {}}],
        )
        self._allow("demo.one", "demo.two")
        item = discover_catalog(self.root)["demo.swap"]
        code, _out, err = run_chain(self.root, item, {})
        self.assertEqual(code, 1)
        payload = json.loads(err)
        self.assertEqual(payload["error"], "chain_dependency_changed")
        self.assertEqual(payload["outcome"], "partial")
        self.assertIn("demo.two", payload["why"])
        self.assertTrue(first.exists())
        self.assertFalse(second.exists())
        finish = [
            row
            for row in (self.root / "state" / "trace.jsonl").read_text(encoding="utf-8").splitlines()
            if json.loads(row).get("kind") == "chain" and json.loads(row).get("phase") == "finish"
        ]
        self.assertEqual(json.loads(finish[-1])["outcome"], "partial")
