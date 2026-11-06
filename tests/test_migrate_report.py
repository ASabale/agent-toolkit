"""tk.migrate exports and applies a manifest without copying state or secrets."""

from __future__ import annotations

import hashlib
import importlib.util
from importlib.machinery import SourceFileLoader
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "tk" / "migrate"

PLAIN_TOOL = """#!/usr/bin/env python3
# @tk-name: bench.plain
# @tk-summary: Writes a marker file when executed; migration tests only
# @tk-safety: read-only
# @tk-output: json | {dry_run, ran}
# @tk-example: tk run bench.plain
# @tk-verified: none

import os
from pathlib import Path

state = Path(os.environ.get("TK_STATE_DIR", "."))
if os.environ.get("TK_DRY_RUN", "0") == "1":
    print({"dry_run": True})
else:
    state.mkdir(parents=True, exist_ok=True)
    (state / "bench-ran").write_text("ran")
    print({"ran": True})
"""

DATED_TOOL = """#!/usr/bin/env python3
# @tk-name: bench.dated
# @tk-summary: Read-only fixture carrying a verified date
# @tk-safety: read-only
# @tk-output: json | {ok}
# @tk-example: tk run bench.dated
# @tk-verified: 2026-10-01

if __name__ == "__main__":
    print({"ok": True})
"""

SKILL_TEXT = "# Agent Toolkit skill fixture\n"


def _chain_text(tool_sha: str) -> str:
    return json.dumps(
        {
            "kind": "chain",
            "name": "bench.chain",
            "summary": "Run the fixture tool once",
            "safety": "read-only",
            "args": [],
            "steps": [{"tool": "bench.plain", "args": {}, "tool_sha256": tool_sha}],
            "output": "json | object",
            "example": "tk run bench.chain",
            "verified": "2026-10-01",
        }
    )


def _make_source(root: Path) -> Path:
    (root / "tools").mkdir(parents=True, exist_ok=True)
    (root / "chains").mkdir(parents=True, exist_ok=True)
    (root / "skills" / "agent-toolkit").mkdir(parents=True, exist_ok=True)
    plain = root / "tools" / "bench.plain"
    plain.write_text(PLAIN_TOOL)
    plain.chmod(0o755)
    dated = root / "tools" / "bench.dated"
    dated.write_text(DATED_TOOL)
    dated.chmod(0o755)
    (root / "chains" / "bench.chain.json").write_text(_chain_text(hashlib.sha256(PLAIN_TOOL.encode()).hexdigest()))
    (root / "skills" / "agent-toolkit" / "SKILL.md").write_text(SKILL_TEXT)
    (root / "VERSION").write_text("0.9.3\n")
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "state" / "policy.json").write_text(json.dumps({"version": 1, "classes": {"destructive": "allow"}}))
    (root / "tools" / "gh_credentials.json").write_text('{"gh_credentials": "ghp_source_only"}')
    return root


def _make_dest(root: Path) -> Path:
    (root / "tools").mkdir(parents=True, exist_ok=True)
    (root / "chains").mkdir(parents=True, exist_ok=True)
    (root / "skills" / "agent-toolkit").mkdir(parents=True, exist_ok=True)
    return root


def _env(extra: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env["TK_ROOT_DIR"] = str(ROOT)
    env["TK_DRY_RUN"] = "0"
    env.update(extra)
    return env


def _run(env: dict[str, str], cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(TOOL)], cwd=str(cwd), env=env, capture_output=True, text=True, check=False
    )


def _payload(proc: subprocess.CompletedProcess) -> dict:
    return json.loads(proc.stdout if proc.returncode == 0 else proc.stderr)


def _tree(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes().hex()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


def _tool_module():
    name = "tk_migrate_tool"
    loader = SourceFileLoader(name, str(TOOL))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MigrateReportTests(unittest.TestCase):
    def test_report_names_catalog_skill_and_gh_without_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_source(root)
            secret = "ghp_migrate_secret_value"
            proc = _run(
                _env(
                    {
                        "TK_ROOT_DIR": str(root),
                        "TK_STATE_DIR": str(root / "state"),
                        "TK_DRY_RUN": "1",
                        "GH_TOKEN": secret,
                        "TK_HOME": str(root / "should-not-exist"),
                    }
                )
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotIn(secret, proc.stdout)
            self.assertNotIn(secret, proc.stderr)
            payload = _payload(proc)
            self.assertTrue(payload["dry_run"])
            self.assertFalse(payload["secrets_copied"])
            self.assertFalse(payload["state_copied"])
            self.assertEqual([row["kind"] for row in payload["copy"]], ["tool", "chain", "skill"])
            self.assertFalse(any("state" in row["path"] for row in payload["copy"]))
            cred = payload["credentials"][0]
            self.assertEqual(cred["name"], "gh")
            self.assertFalse(cred["copied"])
            self.assertIn(cred["where"], {"already in gh", "gh not on PATH"})
            self.assertNotIn("TK_HOME", proc.stdout)
            self.assertFalse((root / "should-not-exist").exists())

    def test_export_lists_manifest_rows_and_skips_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _make_source(root)
            proc = _run(_env({"TK_ARG_ACTION": "export", "TK_ARG_SOURCE": str(root)}))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            manifest = _payload(proc)
            self.assertEqual(manifest["version"], 1)
            self.assertEqual(manifest["source_version"], "0.9.3")
            paths = [row["path"] for row in manifest["files"]]
            self.assertEqual(
                paths,
                ["chains/bench.chain.json", "skills/agent-toolkit/SKILL.md", "tools/bench.dated", "tools/bench.plain"],
            )
            for row in manifest["files"]:
                self.assertEqual(row["sha256"], hashlib.sha256((root / row["path"]).read_bytes()).hexdigest())
                self.assertEqual(row["size"], (root / row["path"]).stat().st_size)
                self.assertEqual(row["executable"], (root / row["path"]).stat().st_mode & 0o111 != 0)
            kinds = {row["path"]: row["kind"] for row in manifest["files"]}
            self.assertEqual(kinds["tools/bench.plain"], "tool")
            self.assertEqual(kinds["chains/bench.chain.json"], "chain")
            self.assertEqual(kinds["skills/agent-toolkit/SKILL.md"], "skill")
            self.assertFalse(any("state" in path or "credentials" in path for path in paths))

    def test_dry_run_apply_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _make_source(root / "source")
            dest = _make_dest(root / "dest")
            before = _tree(dest)
            proc = _run(
                _env(
                    {
                        "TK_ARG_ACTION": "apply",
                        "TK_ARG_SOURCE": str(source),
                        "TK_ARG_DEST": str(dest),
                    }
                )
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = _payload(proc)
            self.assertTrue(payload["dry_run"])
            self.assertEqual(len(payload["plan"]), 4)
            self.assertEqual(_tree(dest), before)
            # TK_DRY_RUN wins over an explicit --apply.
            proc = _run(
                _env(
                    {
                        "TK_ARG_ACTION": "apply",
                        "TK_ARG_SOURCE": str(source),
                        "TK_ARG_DEST": str(dest),
                        "TK_ARG_APPLY": "1",
                        "TK_DRY_RUN": "1",
                    }
                )
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(_payload(proc)["dry_run"])
            self.assertEqual(_tree(dest), before)

    def test_apply_installs_a_new_tool_and_leaves_it_unverified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _make_source(root / "source")
            dest = _make_dest(root / "dest")
            state = root / "state"
            proc = _run(
                _env(
                    {
                        "TK_ARG_ACTION": "apply",
                        "TK_ARG_SOURCE": str(source),
                        "TK_ARG_DEST": str(dest),
                        "TK_ARG_APPLY": "1",
                        "TK_STATE_DIR": str(state),
                    }
                )
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = _payload(proc)
            self.assertFalse(payload["dry_run"])
            self.assertEqual(
                payload["copied"],
                ["chains/bench.chain.json", "skills/agent-toolkit/SKILL.md", "tools/bench.dated", "tools/bench.plain"],
            )
            self.assertTrue(all(row["ok"] for row in payload["checks"]))
            copied_text = (dest / "tools" / "bench.dated").read_text()
            self.assertIn("# @tk-verified: none", copied_text)
            self.assertNotIn("2026-10-01", copied_text)
            self.assertTrue(os.access(dest / "tools" / "bench.plain", os.X_OK))
            # The imported tool was checked statically, never executed.
            self.assertFalse((state / "bench-ran").exists())
            self.assertFalse((dest / "state").exists())
            self.assertFalse((dest / "tools" / "gh_credentials.json").exists())
            self.assertTrue((source / "VERSION").is_file())

    def test_apply_checks_the_written_destination_files_not_the_cwd(self):
        """Static checks read the destination bytes, never a cwd-relative lookalike."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _make_source(root / "source")
            dest = _make_dest(root / "dest")
            proc = _run(
                _env(
                    {
                        "TK_ARG_ACTION": "apply",
                        "TK_ARG_SOURCE": str(source),
                        "TK_ARG_DEST": str(dest),
                        "TK_ARG_APPLY": "1",
                        "TK_STATE_DIR": str(root / "state"),
                    }
                ),
                cwd=source,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = _payload(proc)
            self.assertEqual([row["name"] for row in payload["checks"]], ["bench.chain", "bench.dated", "bench.plain"])
            self.assertTrue(all(row["ok"] for row in payload["checks"]))
            self.assertTrue((dest / "chains" / "bench.chain.json").is_file())

    def test_compiled_cache_files_are_neither_exported_nor_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _make_source(root / "source")
            cache = source / "tools" / "tk" / "__pycache__"
            cache.mkdir(parents=True)
            (cache / "migratecpython-314.pyc").write_bytes(b"\x00not a tool\n")
            dest = _make_dest(root / "dest")
            proc = _run(_env({"TK_ARG_ACTION": "export", "TK_ARG_SOURCE": str(source)}))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            paths = [row["path"] for row in _payload(proc)["files"]]
            self.assertFalse(any("__pycache__" in path or path.endswith(".pyc") for path in paths))
            proc = _run(
                _env(
                    {
                        "TK_ARG_ACTION": "apply",
                        "TK_ARG_SOURCE": str(source),
                        "TK_ARG_DEST": str(dest),
                        "TK_ARG_APPLY": "1",
                        "TK_STATE_DIR": str(root / "state"),
                    }
                )
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertFalse((dest / "tools" / "tk" / "__pycache__").exists())

    def test_same_content_destination_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _make_source(root / "source")
            dest = _make_dest(root / "dest")
            draft = PLAIN_TOOL  # already @tk-verified: none
            (dest / "tools" / "bench.plain").write_text(draft)
            before = _tree(dest)
            proc = _run(
                _env(
                    {
                        "TK_ARG_ACTION": "apply",
                        "TK_ARG_SOURCE": str(source),
                        "TK_ARG_DEST": str(dest),
                        "TK_ARG_APPLY": "1",
                        "TK_STATE_DIR": str(root / "state"),
                    }
                )
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = _payload(proc)
            self.assertIn("tools/bench.plain", payload["skipped"])
            self.assertNotIn("tools/bench.plain", payload["copied"])
            self.assertNotIn("tools/bench.plain", [row["path"] for row in payload["created"]])
            self.assertEqual((dest / "tools" / "bench.plain").read_text(), draft)
            self.assertEqual(before, {rel: digest for rel, digest in _tree(dest).items() if rel in before})

    def test_different_content_collision_keeps_existing_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _make_source(root / "source")
            dest = _make_dest(root / "dest")
            (dest / "tools" / "bench.plain").write_text("do not overwrite me\n")
            proc = _run(
                _env(
                    {
                        "TK_ARG_ACTION": "apply",
                        "TK_ARG_SOURCE": str(source),
                        "TK_ARG_DEST": str(dest),
                        "TK_ARG_APPLY": "1",
                        "TK_STATE_DIR": str(root / "state"),
                    }
                )
            )
            self.assertEqual(proc.returncode, 1, proc.stderr)
            payload = _payload(proc)
            self.assertEqual(payload["error"], "collision")
            self.assertEqual((dest / "tools" / "bench.plain").read_text(), "do not overwrite me\n")
            removed = {Path(row).relative_to(dest).as_posix() for row in payload["removed"]}
            self.assertEqual(removed, {"chains/bench.chain.json", "skills/agent-toolkit/SKILL.md", "tools/bench.dated"})
            for rel in removed:
                self.assertFalse((dest / rel).exists())

    def test_manifest_hash_mismatch_copies_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _make_source(root / "source")
            dest = _make_dest(root / "dest")
            manifest = json.loads(
                _run(_env({"TK_ARG_ACTION": "export", "TK_ARG_SOURCE": str(source)})).stdout
            )
            manifest["files"][0]["sha256"] = "0" * 64
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest))
            proc = _run(
                _env(
                    {
                        "TK_ARG_ACTION": "apply",
                        "TK_ARG_SOURCE": str(source),
                        "TK_ARG_DEST": str(dest),
                        "TK_ARG_APPLY": "1",
                        "TK_ARG_MANIFEST": str(manifest_path),
                    }
                )
            )
            self.assertEqual(proc.returncode, 1, proc.stderr)
            payload = _payload(proc)
            self.assertEqual(payload["error"], "refused")
            self.assertIn("manifest hash mismatch", payload["why"])
            self.assertEqual(_tree(dest), {})

    def _export(self, source: Path) -> dict:
        proc = _run(_env({"TK_ARG_ACTION": "export", "TK_ARG_SOURCE": str(source), "TK_STATE_DIR": str(source.parent / "state")}))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def _apply_manifest(self, root: Path, source: Path, dest: Path, manifest: dict) -> subprocess.CompletedProcess:
        path = root / "manifest.json"
        path.write_text(json.dumps(manifest))
        return _run(
            _env(
                {
                    "TK_ARG_ACTION": "apply",
                    "TK_ARG_SOURCE": str(source),
                    "TK_ARG_DEST": str(dest),
                    "TK_ARG_APPLY": "1",
                    "TK_ARG_MANIFEST": str(path),
                    "TK_STATE_DIR": str(root / "state"),
                }
            )
        )

    def test_file_added_after_export_is_absent_from_copied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _make_source(root / "source")
            dest = _make_dest(root / "dest")
            manifest = self._export(source)
            extra = source / "tools" / "bench.extra"
            extra.write_text(PLAIN_TOOL.replace("bench.plain", "bench.extra"))
            extra.chmod(0o755)
            proc = self._apply_manifest(root, source, dest, manifest)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            copied = _payload(proc)["copied"]
            self.assertNotIn("tools/bench.extra", copied)
            self.assertEqual(copied, [row["path"] for row in manifest["files"]])
            self.assertFalse((dest / "tools" / "bench.extra").exists())

    def test_path_deleted_from_manifest_is_absent_from_copied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _make_source(root / "source")
            dest = _make_dest(root / "dest")
            manifest = self._export(source)
            manifest["files"] = [row for row in manifest["files"] if row["path"] != "tools/bench.dated"]
            proc = self._apply_manifest(root, source, dest, manifest)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            copied = _payload(proc)["copied"]
            self.assertNotIn("tools/bench.dated", copied)
            self.assertEqual(copied, [row["path"] for row in manifest["files"]])
            self.assertFalse((dest / "tools" / "bench.dated").exists())

    def test_byte_change_after_export_copies_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _make_source(root / "source")
            dest = _make_dest(root / "dest")
            manifest = self._export(source)
            target = source / "tools" / "bench.plain"
            target.write_bytes(target.read_bytes() + b"\n")
            proc = self._apply_manifest(root, source, dest, manifest)
            self.assertEqual(proc.returncode, 1, proc.stderr)
            payload = _payload(proc)
            self.assertEqual(payload["error"], "refused")
            self.assertIn("manifest hash mismatch", payload["why"])
            self.assertEqual(_tree(dest), {})

    def test_duplicate_manifest_path_fails_before_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _make_source(root / "source")
            dest = _make_dest(root / "dest")
            manifest = self._export(source)
            manifest["files"] = [manifest["files"][0], dict(manifest["files"][0])]
            proc = self._apply_manifest(root, source, dest, manifest)
            self.assertEqual(proc.returncode, 1, proc.stderr)
            payload = _payload(proc)
            self.assertEqual(payload["error"], "refused")
            self.assertIn("manifest duplicate path", payload["why"])
            self.assertEqual(_tree(dest), {})

    def test_parent_and_absolute_manifest_paths_fail_before_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _make_source(root / "source")
            dest = _make_dest(root / "dest")
            for rel in ("../escape.txt", "/etc/passwd"):
                proc = self._apply_manifest(root, source, dest, {"version": 1, "files": [{"path": rel, "sha256": "0" * 64}]})
                self.assertEqual(proc.returncode, 1, proc.stderr)
                payload = _payload(proc)
                self.assertEqual(payload["error"], "refused")
                self.assertIn("manifest path refused", payload["why"])
                self.assertEqual(_tree(dest), {})

    def test_listed_path_missing_on_disk_fails_before_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _make_source(root / "source")
            dest = _make_dest(root / "dest")
            manifest = self._export(source)
            (source / "tools" / "bench.plain").unlink()
            proc = self._apply_manifest(root, source, dest, manifest)
            self.assertEqual(proc.returncode, 1, proc.stderr)
            payload = _payload(proc)
            self.assertEqual(payload["error"], "refused")
            self.assertIn("manifest path missing", payload["why"])
            self.assertEqual(_tree(dest), {})

    def test_export_manifest_copies_exactly_its_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _make_source(root / "source")
            dest = _make_dest(root / "dest")
            manifest = self._export(source)
            proc = self._apply_manifest(root, source, dest, manifest)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = _payload(proc)
            self.assertEqual(payload["copied"], [row["path"] for row in manifest["files"]])
            self.assertEqual(payload["skipped"], [])
            self.assertEqual(set(payload["copied"]), {row["path"] for row in manifest["files"]})

    def test_traversal_and_source_symlink_escape_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _make_source(root / "source")
            dest = _make_dest(root / "dest")
            outside = root / "outside"
            outside.mkdir()
            (outside / "escape.txt").write_text("outside\n")

            manifest_path = root / "bad-manifest.json"
            manifest_path.write_text(json.dumps({"version": 1, "files": [{"path": "../escape.txt", "sha256": "0" * 64}]}))
            proc = _run(
                _env(
                    {
                        "TK_ARG_ACTION": "apply",
                        "TK_ARG_SOURCE": str(source),
                        "TK_ARG_DEST": str(root / "dest"),
                        "TK_ARG_APPLY": "1",
                        "TK_ARG_MANIFEST": str(manifest_path),
                    }
                )
            )
            self.assertEqual(proc.returncode, 1, proc.stderr)
            self.assertEqual(_payload(proc)["error"], "refused")

            proc = _run(_env({"TK_ARG_ACTION": "apply", "TK_ARG_SOURCE": str(source / ".."), "TK_ARG_DEST": str(dest)}))
            self.assertEqual(proc.returncode, 2, proc.stderr)
            self.assertEqual(_payload(proc)["error"], "missing_flag")

            os.symlink(outside / "escape.txt", source / "tools" / "link-out")
            proc = _run(_env({"TK_ARG_ACTION": "export", "TK_ARG_SOURCE": str(source)}))
            self.assertEqual(proc.returncode, 1, proc.stderr)
            payload = _payload(proc)
            self.assertEqual(payload["error"], "refused")
            self.assertIn("symlink leaves source", payload["why"])

    def test_destination_symlink_escape_copies_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _make_source(root / "source")
            outside = root / "outside"
            outside.mkdir()
            dest = root / "dest"
            (dest / "chains").mkdir(parents=True, exist_ok=True)
            os.symlink(outside, dest / "tools")
            proc = _run(
                _env(
                    {
                        "TK_ARG_ACTION": "apply",
                        "TK_ARG_SOURCE": str(source),
                        "TK_ARG_DEST": str(dest),
                        "TK_ARG_APPLY": "1",
                        "TK_STATE_DIR": str(root / "state"),
                    }
                )
            )
            self.assertEqual(proc.returncode, 1, proc.stderr)
            payload = _payload(proc)
            self.assertEqual(payload["error"], "dest_escape")
            self.assertEqual(sorted(p.name for p in outside.iterdir()), [])
            self.assertEqual(sorted(p.name for p in (dest / "chains").iterdir()), [])

    def test_occupant_that_wins_the_name_is_left_in_place(self):
        """The exclusive create never replaces the winner; the run aborts instead."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = _make_source(root / "source")
            dest = _make_dest(root / "dest")
            (dest / "tools" / "bench.plain").mkdir()
            proc = _run(
                _env(
                    {
                        "TK_ARG_ACTION": "apply",
                        "TK_ARG_SOURCE": str(source),
                        "TK_ARG_DEST": str(dest),
                        "TK_ARG_APPLY": "1",
                        "TK_STATE_DIR": str(root / "state"),
                    }
                )
            )
            self.assertEqual(proc.returncode, 1, proc.stderr)
            payload = _payload(proc)
            self.assertEqual(payload["error"], "collision")
            self.assertTrue((dest / "tools" / "bench.plain").is_dir())
            self.assertEqual(sorted(p.name for p in (dest / "tools" / "bench.plain").iterdir()), [])
            self.assertFalse((dest / "tools" / "bench.dated").exists())
            removed = {Path(row).relative_to(dest).as_posix() for row in payload["removed"]}
            self.assertNotIn("tools/bench.plain", removed)

    def test_exclusive_create_never_replaces_an_existing_name(self):
        module = _tool_module()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "victim"
            path.write_text("original bytes\n")
            error = module._exclusive_write(path, b"rewritten\n", True)
            self.assertEqual(error, "exists")
            self.assertEqual(path.read_bytes(), b"original bytes\n")

    def test_rollback_removes_only_its_own_unmodified_files(self):
        module = _tool_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mine = root / "mine"
            mine.write_bytes(b"mine\n")
            mine_digest = hashlib.sha256(b"mine\n").hexdigest()
            tampered = root / "tampered"
            tampered.write_bytes(b"tampered\n")
            tampered_digest = hashlib.sha256(b"tampered\n").hexdigest()
            tampered.write_bytes(b"tampered\nchanged\n")
            preexisting = root / "preexisting"
            preexisting.write_bytes(b"preexisting\n")
            removed = module._rollback([(mine, mine_digest), (tampered, tampered_digest)])
            self.assertEqual([Path(row).name for row in removed], ["mine"])
            self.assertFalse(mine.exists())
            self.assertTrue(tampered.exists())
            self.assertTrue(preexisting.exists())

    def test_unknown_action_is_rejected(self):
        proc = _run(_env({"TK_ARG_ACTION": "copy"}))
        self.assertEqual(proc.returncode, 2, proc.stderr)
        payload = _payload(proc)
        self.assertEqual(payload["error"], "unknown_action")
        self.assertEqual(payload["fix"], "tk run tk.migrate --action report")


if __name__ == "__main__":
    unittest.main()
