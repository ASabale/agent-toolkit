"""Validation, observed runs, and provenance stay separate facts."""

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lib.catalog import check_item, format_info_output, parse_tool_header
from lib.evolver import (
    evolve_report,
    evidence_view,
    execution_draft,
    mark_execution_draft,
    record_validation,
    write_state_json,
)
from lib.runner import _sha256_file, run_chain, run_tool


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

    def test_header_provenance_is_not_approval_and_does_not_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self._tool(root, "read-only")
            text = path.read_text(encoding="utf-8").replace(
                "# @tk-verified: none\n",
                "# @tk-verified: none\n# @tk-provenance: local\n",
            )
            path.write_text(text, encoding="utf-8")
            self.assertEqual(parse_tool_header(path).get("provenance"), "local")
            view = evidence_view(root, self._item(path))
            self.assertEqual(view["provenance"], "draft")
            self.assertTrue(execution_draft(root, self._item(path)))
            code, out, err = run_tool(root, self._item(path), {}, [], False, None)
            self.assertEqual(code, 2, err)
            self.assertEqual(out, "")
            self.assertEqual(json.loads(err)["error"], "policy_denied")

    def test_verified_none_without_a_draft_record_is_not_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self._tool(root, "read-only")
            view = evidence_view(root, self._item(path))
            self.assertEqual(view["provenance"], "draft")
            self.assertFalse(execution_draft(root, self._item(path)))
            code, out, err = run_tool(root, self._item(path), {}, [], False, None)
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["ok"], True)

    def test_invalid_evidence_blocks_class_allow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self._tool(root, "read-only")
            state = Path(self._state.name)
            state.mkdir(parents=True, exist_ok=True)
            (state / "evidence.json").write_text("{", encoding="utf-8")
            code, _out, err = run_tool(root, self._item(path), {}, [], False, None)
            self.assertEqual(code, 2, err)
            self.assertEqual(json.loads(err)["error"], "policy_denied")
            (state / "evidence.json").write_text('{"version": 2, "items": {}}\n', encoding="utf-8")
            code, _out, err = run_tool(root, self._item(path), {}, [], False, None)
            self.assertEqual(code, 2, err)
            self.assertEqual(json.loads(err)["error"], "policy_denied")

    def test_exact_approval_does_not_survive_a_byte_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self._tool(root, "read-only")
            digest = _sha256_file(path)
            write_state_json(
                root,
                "evidence.json",
                {
                    "version": 1,
                    "items": {
                        "demo.echo": {
                            "provenance": "local",
                            "approved_sha256": digest,
                            "validation": digest,
                        }
                    },
                },
            )
            self.assertFalse(execution_draft(root, self._item(path)))
            code, _out, err = run_tool(root, self._item(path), {}, [], False, None)
            self.assertEqual(code, 0, err)
            path.write_bytes(path.read_bytes() + b"\n# changed\n")
            record_validation(root, ["demo.echo"])
            view = evidence_view(root, self._item(path))
            self.assertEqual(view["provenance"], "draft")
            self.assertNotEqual(view["validation_sha256"], digest)
            self.assertTrue(execution_draft(root, self._item(path)))
            code, out, err = run_tool(root, self._item(path), {}, [], False, None)
            self.assertEqual(code, 2, err)
            self.assertEqual(out, "")
            self.assertEqual(json.loads(err)["error"], "policy_denied")

    def test_saved_draft_runs_only_with_exact_hash_allow_including_a_chain(self) -> None:
        from lib.evolver import save_tool, save_chain
        from lib.catalog import discover_catalog

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, _out, err = save_tool(
                root,
                "demo.echo",
                "Echo",
                from_cmd="printf '%s\\n' '{\"ok\":true}'",
            )
            self.assertEqual(code, 0, err)
            path = root / "tools" / "demo" / "echo"
            self.assertIn("# @tk-verified: none", path.read_text(encoding="utf-8"))
            self.assertNotIn("@tk-provenance: local", path.read_text(encoding="utf-8"))
            item = discover_catalog(root)["demo.echo"]
            self.assertTrue(execution_draft(root, item))
            code, out, err = run_tool(root, item, {}, [], False, None)
            self.assertEqual(code, 2, err)
            self.assertEqual(out, "")
            self.assertEqual(json.loads(err)["error"], "policy_denied")
            code, _, err = save_chain(
                root, "demo.pipe", "Pipe", steps=[{"tool": "demo.echo", "args": {}}]
            )
            self.assertEqual(code, 0, err)
            chain = discover_catalog(root)["demo.pipe"]
            code, _out, err = run_chain(root, chain, {})
            self.assertEqual(code, 2, err)
            self.assertEqual(json.loads(err)["error"], "policy_denied")
            write_state_json(
                root,
                "policy.json",
                {
                    "version": 1,
                    "classes": {
                        "read-only": "allow",
                        "mutating": "confirm",
                        "destructive": "deny",
                    },
                    "rules": [
                        {
                            "rank": "hash",
                            "sha256": _sha256_file(path),
                            "decision": "allow",
                        }
                    ],
                },
            )
            code, out, err = run_tool(root, item, {}, [], False, None)
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["ok"], True)
            code, out, err = run_chain(root, chain, {})
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["ok"], True)
            stored = json.loads((Path(self._state.name) / "evidence.json").read_text(encoding="utf-8"))
            self.assertIs(stored["items"]["demo.echo"]["blocked"], True)
            self.assertEqual(stored["items"]["demo.echo"]["provenance"], "draft")

    def test_mark_execution_draft_blocks_an_existing_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self._tool(root, "read-only")
            mark_execution_draft(root, "demo.echo")
            code, _out, err = run_tool(root, self._item(path), {}, [], False, None)
            self.assertEqual(code, 2, err)
            self.assertEqual(json.loads(err)["error"], "policy_denied")


if __name__ == "__main__":
    unittest.main()
