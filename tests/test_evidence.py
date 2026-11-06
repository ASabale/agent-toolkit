"""Validation, observed runs, and provenance stay separate facts."""

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib.catalog import check_item, format_info_output
from lib.evolver import evolve_report, evidence_view, record_validation
from lib.runner import run_tool


def _bash_tool(name: str, safety: str) -> str:
    return (
        "#!/usr/bin/env bash\n"
        f"# @tk-name: {name}\n"
        "# @tk-summary: Echo a target id\n"
        f"# @tk-safety: {safety}\n"
        "# @tk-output: json | Distilled object\n"
        f"# @tk-example: tk run {name}\n"
        "# @tk-verified: none\n"
        "\n"
        "if [[ \"${TK_DRY_RUN:-0}\" == \"1\" ]]; then\n"
        "  printf '%s\\n' '{\"dry_run\":true}'\n"
        "  exit 0\n"
        "fi\n"
        "printf '%s\\n' '{\"ok\":true}'\n"
    )


class EvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._state = tempfile.TemporaryDirectory()
        self._old_state = os.environ.get("TK_STATE_DIR")
        os.environ["TK_STATE_DIR"] = self._state.name

    def tearDown(self) -> None:
        if self._old_state is None:
            os.environ.pop("TK_STATE_DIR", None)
        else:
            os.environ["TK_STATE_DIR"] = self._old_state
        self._state.cleanup()

    def _tool(self, root: Path, safety: str) -> Path:
        path = root / "tools" / "demo" / "echo"
        path.parent.mkdir(parents=True)
        path.write_text(_bash_tool("demo.echo", safety), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return path

    def _item(self, path: Path) -> dict:
        return {"name": "demo.echo", "path": str(path), "kind": "tool", "safety": "read-only", "verified": "none"}

    def test_check_then_byte_change_hides_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self._tool(root, "read-only")
            checked = check_item(root, "demo.echo")
            self.assertTrue(checked["ok"], checked)
            record_validation(root, ["demo.echo"])
            shown = format_info_output({**self._item(path), **evidence_view(root, self._item(path))})
            digest = evidence_view(root, self._item(path))["content_sha256"]
            self.assertIn(f"validation: static_passed {digest}", shown)
            path.write_bytes(path.read_bytes() + b"\n# changed\n")
            changed = format_info_output({**self._item(path), **evidence_view(root, self._item(path))})
            self.assertIn("validation: none", changed)
            self.assertNotIn("static_passed", changed)

    def test_run_ok_does_not_authorize_or_set_local(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self._tool(root, "read-only")
            code, _out, err = run_tool(root, self._item(path), {}, [], False, None)
            self.assertEqual(code, 0, err)
            shown = format_info_output({**self._item(path), **evidence_view(root, self._item(path))})
            self.assertIn("observed_run: ok ", shown)
            self.assertIn("provenance: draft", shown)
            self.assertNotIn("provenance: local", shown)
            policy = Path(self._state.name) / "policy.json"
            if policy.is_file():
                document = json.loads(policy.read_text(encoding="utf-8"))
                self.assertEqual(document.get("rules"), [])

    def test_signed_header_is_not_local_provenance(self) -> None:
        text = format_info_output(
            {
                "name": "demo.echo",
                "kind": "tool",
                "safety": "read-only",
                "summary": "Echo a target id",
                "args": [],
                "output": "json | Distilled object",
                "example": "tk run demo.echo",
                "verified": "signed",
                "provenance": "signed",
            }
        )
        self.assertIn("provenance: draft", text)
        self.assertNotIn("provenance: signed", text)
        self.assertNotIn("provenance: local", text)

    def test_destructive_evolve_does_not_change_file_or_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self._tool(root, "destructive")
            before = path.read_bytes()
            state = Path(self._state.name)
            state.mkdir(parents=True, exist_ok=True)
            (state / "events.jsonl").write_text(
                json.dumps({"event": "run_ok", "name": "demo.echo"}) + "\n",
                encoding="utf-8",
            )
            evolve_report(root)
            self.assertEqual(path.read_bytes(), before)
            policy = state / "policy.json"
            if policy.is_file():
                document = json.loads(policy.read_text(encoding="utf-8"))
                self.assertEqual(document.get("rules"), [])

    def test_evidence_write_failure_leaves_tool_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self._tool(root, "read-only")
            before = path.read_bytes()
            state = Path(self._state.name)
            state.mkdir(parents=True, exist_ok=True)
            (state / "events.jsonl").write_text(
                json.dumps({"event": "run_ok", "name": "demo.echo"}) + "\n",
                encoding="utf-8",
            )
            with patch("lib.evolver.write_state_json", side_effect=OSError("disk")):
                evolve_report(root)
            self.assertEqual(path.read_bytes(), before)
            self.assertIn("# @tk-verified: none", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
