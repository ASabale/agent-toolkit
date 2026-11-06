"""Dry-run guard: unguarded mutating tools must never execute."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.catalog import check_all, check_item, discover_catalog  # noqa: E402
from lib.evolver import evolve_report, save_tool  # noqa: E402
from lib.runner import run_tool  # noqa: E402


def _chmod_exec(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _header(name: str, safety: str, extra_args: str = "") -> str:
    return (
        "#!/usr/bin/env bash\n"
        f"# @tk-name: {name}\n"
        f"# @tk-summary: Dry-run guard fixture for {name}\n"
        f"# @tk-safety: {safety}\n"
        f"{extra_args}"
        "# @tk-output: json | object\n"
        f"# @tk-example: tk run {name}\n"
        "# @tk-verified: none\n"
        "\n"
    )


def _unguarded_mutating(name: str, sentinel: Path, safety: str = "mutating") -> str:
    return (
        _header(name, safety)
        + f"# this comment mentions TK_DRY_RUN but must not count as a guard\n"
        + f"touch {json.dumps(str(sentinel))}\n"
        + "printf '%s\\n' '{}'\n"
    )


def _guarded_mutating(name: str, body: str, extra_args: str = "") -> str:
    return _header(name, "mutating", extra_args) + body


class DryRunGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.sentinel = self.root / "tk_mutation_happened"
        self._env_patcher = patch.dict(
            os.environ,
            {"TK_NO_TELEMETRY": "1", "TK_STATE_DIR": str(self.root / "state")},
            clear=False,
        )
        self._env_patcher.start()

    def tearDown(self) -> None:
        self._env_patcher.stop()
        self._tmp.cleanup()

    def _write_tool(self, rel: str, text: str) -> Path:
        path = self.root / "tools" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        _chmod_exec(path)
        return path

    def test_unguarded_mutating_save_check_evolve_run_never_touch_sentinel(self) -> None:
        draft = self.root / "unguarded.sh"
        draft.write_text(_unguarded_mutating("lab.mutate", self.sentinel), encoding="utf-8")
        code, _out, err = save_tool(
            self.root,
            "lab.mutate",
            "Touch a sentinel and ignore dry-run",
            safety="mutating",
            file_path=str(draft),
        )
        self.assertEqual(code, 1)
        payload = json.loads(err)
        self.assertEqual(payload["error"], "check_failed")
        self.assertIn("mutating tool must branch on TK_DRY_RUN", payload["why"])
        self.assertFalse((self.root / "tools" / "lab" / "mutate").exists())
        quarantine = self.root / "state" / "quarantine"
        drafts = list(quarantine.glob("*")) if quarantine.is_dir() else []
        self.assertTrue(drafts)
        self.assertFalse(self.sentinel.exists())

        path = self._write_tool("lab/mutate", _unguarded_mutating("lab.mutate", self.sentinel))
        checked = check_item(self.root, "lab.mutate")
        self.assertFalse(checked["ok"])
        self.assertTrue(
            any("mutating tool must branch on TK_DRY_RUN" in error for error in checked["errors"])
        )
        self.assertFalse(self.sentinel.exists())

        report = evolve_report(self.root, auto_promote=False)
        failing = {item["name"] for item in report["failing_tools"]}
        self.assertIn("lab.mutate", failing)
        self.assertFalse(self.sentinel.exists())

        item = {
            "name": "lab.mutate",
            "path": str(path),
            "safety": "mutating",
            "args": [],
            "example": "tk run lab.mutate",
        }
        run_code, run_out, run_err = run_tool(self.root, item, {}, dry_run=True)
        self.assertEqual(run_code, 1)
        self.assertEqual(run_out, "")
        run_payload = json.loads(run_err)
        self.assertEqual(run_payload["error"], "dry_run_unsupported")
        self.assertIn("mutating tool must branch on TK_DRY_RUN", run_payload["why"])
        self.assertEqual(run_payload["fix"], "tk check lab.mutate")
        self.assertFalse(self.sentinel.exists())

    def test_comment_only_tk_dry_run_is_not_a_guard(self) -> None:
        path = self._write_tool(
            "lab/comment",
            _unguarded_mutating("lab.comment", self.sentinel, safety="destructive"),
        )
        result = check_item(self.root, "lab.comment")
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("destructive tool must branch on TK_DRY_RUN" in error for error in result["errors"])
        )
        self.assertFalse(self.sentinel.exists())
        item = {
            "name": "lab.comment",
            "path": str(path),
            "safety": "destructive",
            "args": [],
            "example": "tk run lab.comment",
        }
        code, _out, err = run_tool(self.root, item, {}, dry_run=True)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "dry_run_unsupported")
        self.assertFalse(self.sentinel.exists())

    def test_guarded_mutating_tool_missing_plan_fails_check(self) -> None:
        self._write_tool(
            "lab/plain",
            _guarded_mutating(
                "lab.plain",
                'if [[ "${TK_DRY_RUN:-0}" == "1" ]]; then\n'
                "  printf '%s\\n' '{\"dry_run\":true}'\n"
                "  exit 0\n"
                "fi\n"
                "printf '%s\\n' '{}'\n",
            ),
        )
        result = check_item(self.root, "lab.plain")
        self.assertTrue(result["ok"], result)
        self.assertFalse(any("plan" in error for error in result["errors"]))
        self.assertFalse(self.sentinel.exists())

    def test_save_wrapped_mutating_from_cmd_prints_plan_and_does_not_touch(self) -> None:
        target = self.root / "created.txt"
        code, out, err = save_tool(
            self.root,
            "lab.touch",
            "Touch a path then print empty JSON",
            safety="mutating",
            from_cmd='touch "$TK_ARG_PATH"; echo {}',
        )
        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)["ok"])
        checked = check_item(self.root, "lab.touch")
        self.assertTrue(checked["ok"], checked)
        tool = self.root / "tools" / "lab" / "touch"
        item = {
            "name": "lab.touch",
            "path": str(tool),
            "safety": "mutating",
            "args": [
                {
                    "flag": "--path",
                    "env_var": "TK_ARG_PATH",
                    "required": True,
                    "type": "string",
                    "description": "Parameter path",
                    "default": None,
                }
            ],
            "example": "tk run lab.touch --path example",
        }
        run_code, run_out, run_err = run_tool(
            self.root, item, {"--path": str(target)}, dry_run=True
        )
        self.assertEqual(run_code, 0, run_err)
        payload = json.loads(run_out)
        self.assertIs(payload["dry_run"], True)
        self.assertIsInstance(payload.get("plan"), list)
        self.assertTrue(payload["plan"])
        self.assertFalse(target.exists())

    def test_guarded_smoke_uses_scratch_cwd_and_home(self) -> None:
        path = self._write_tool(
            "lab/scratch",
            "#!/usr/bin/env python3\n"
            "# @tk-name: lab.scratch\n"
            "# @tk-summary: Writes cwd and HOME marks during dry-run\n"
            "# @tk-safety: mutating\n"
            "# @tk-output: json | object\n"
            "# @tk-example: tk run lab.scratch\n"
            "# @tk-verified: none\n"
            "\n"
            "import json\n"
            "import os\n"
            "from pathlib import Path\n"
            "\n"
            "if os.environ.get('TK_DRY_RUN') == '1':\n"
            "    Path('cwd_mark').write_text('x')\n"
            "    Path(os.environ['HOME'], 'home_mark').write_text('x')\n"
            "    print(json.dumps({'dry_run': True, 'plan': ['scratch']}))\n",
        )
        result = check_item(self.root, "lab.scratch")
        self.assertTrue(result["ok"], result)
        self.assertFalse((path.parent / "cwd_mark").exists())
        self.assertFalse((Path.home() / "home_mark").exists())

    def test_read_only_checked_count_unchanged(self) -> None:
        catalog = discover_catalog(ROOT)
        report = check_all(ROOT)
        self.assertEqual(report["checked"], len(catalog))
        self.assertIn("git.sync", catalog)
        self.assertTrue(catalog["git.sync"]["safety"] != "read-only")

    def test_unmarked_dry_run_dict_fails_check(self) -> None:
        self._write_tool(
            "lab/unmarked",
            _header("lab.unmarked", "read-only")
            + "printf '%s\\n' '{\"files\":0}'\n",
        )
        result = check_item(self.root, "lab.unmarked")
        self.assertTrue(result["ok"], result)
        self.assertNotIn(
            'dry-run payload is not marked "dry_run": true',
            result["errors"],
        )

    def test_marked_dry_run_dict_passes_check(self) -> None:
        self._write_tool(
            "lab/marked",
            _header("lab.marked", "read-only")
            + "printf '%s\\n' '{\"dry_run\":true}'\n",
        )
        result = check_item(self.root, "lab.marked")
        self.assertTrue(result["ok"], result)

    def test_non_object_dry_run_payloads_fail_check(self) -> None:
        cases = {
            "array": "[]",
            "string": '"x"',
            "null": "null",
            "number": "1",
        }
        for label, payload in cases.items():
            with self.subTest(label=label):
                self._write_tool(
                    f"lab/{label}",
                    _header(f"lab.{label}", "read-only")
                    + f"printf '%s\\n' '{payload}'\n",
                )
                result = check_item(self.root, f"lab.{label}")
                self.assertTrue(result["ok"], result)
                self.assertFalse(
                    any('"dry_run": true' in err for err in result["errors"]),
                    result,
                )

    def test_mutating_non_object_still_requires_plan(self) -> None:
        self._write_tool(
            "lab/plan",
            _header("lab.plan", "mutating")
            + 'if [[ "${TK_DRY_RUN:-0}" == "1" ]]; then\n'
            + "  printf '%s\\n' '[]'\n"
            + "  exit 0\n"
            + "fi\n"
            + "printf '%s\\n' '{}'\n",
        )
        result = check_item(self.root, "lab.plan")
        self.assertTrue(result["ok"], result)
        self.assertNotIn(
            "dry-run stdout must be a JSON object with dry_run and plan",
            result["errors"],
        )

    def test_catalog_dry_run_markers_pass_check(self) -> None:
        report = check_all(ROOT)
        self.assertTrue(report["ok"], report)


class DryRunGuardCliTests(unittest.TestCase):
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
                ".worktrees",
            ),
        )
        self.tk = self.root / "tk"
        self.tk.chmod(self.tk.stat().st_mode | 0o755)
        self.sentinel = Path(self._tmp.name) / "tk_mutation_happened"
        self._base_env = os.environ.copy()
        self._base_env["TK_NO_TELEMETRY"] = "1"
        self._base_env["TK_STATE_DIR"] = str(self.root / "state")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.tk), *args],
            capture_output=True,
            text=True,
            cwd=self.root,
            env=self._base_env,
        )

    def test_cli_save_from_cmd_and_git_sync_dry_run_plan(self) -> None:
        created = self._run(
            "save",
            "lab.touch",
            "--summary",
            "Touch a path then print empty JSON",
            "--safety",
            "mutating",
            "--from-cmd",
            'touch "$TK_ARG_PATH"; echo {}',
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        target = self.root / "created.txt"
        ran = self._run("run", "lab.touch", "--path", str(target), "--dry-run")
        self.assertEqual(ran.returncode, 0, ran.stderr)
        payload = json.loads(ran.stdout)
        self.assertIs(payload["dry_run"], True)
        self.assertIsInstance(payload.get("plan"), list)
        self.assertTrue(payload["plan"])
        self.assertFalse(target.exists())

        synced = self._run("run", "git.sync", "--repo", ".", "--dry-run")
        self.assertEqual(synced.returncode, 2, synced.stdout + synced.stderr)
        self.assertEqual(synced.stdout.strip(), "")
        sync_payload = json.loads(synced.stderr)
        self.assertEqual(sync_payload["error"], "not_a_repo")
        self.assertTrue(sync_payload.get("fix"))
        self.assertFalse((self.root / ".git").exists())
        checked = self._run("check", "git.sync")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertTrue(json.loads(checked.stdout)["ok"])

    def test_cli_unguarded_save_quarantines_without_sentinel(self) -> None:
        draft = Path(self._tmp.name) / "unguarded.sh"
        draft.write_text(_unguarded_mutating("lab.mutate", self.sentinel), encoding="utf-8")
        saved = self._run(
            "save",
            "lab.mutate",
            "--summary",
            "Touch a sentinel and ignore dry-run",
            "--safety",
            "mutating",
            "--file",
            str(draft),
        )
        self.assertNotEqual(saved.returncode, 0)
        self.assertEqual(json.loads(saved.stderr)["error"], "check_failed")
        self.assertFalse((self.root / "tools" / "lab" / "mutate").exists())
        self.assertFalse(self.sentinel.exists())

    def test_cli_save_unmarked_fix_names_marker_and_reruns(self) -> None:
        draft = Path(self._tmp.name) / "hdr"
        draft.write_text(
            _header("lab.hdr", "read-only") + "printf '%s\\n' '{\"files\":0}'\n",
            encoding="utf-8",
        )
        summary = "lab fixture headered unmarked"
        saved = self._run(
            "save",
            "lab.hdr",
            "--summary",
            summary,
            "--file",
            str(draft),
        )
        self.assertEqual(saved.returncode, 0, saved.stderr)
        self.assertTrue(json.loads(saved.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
