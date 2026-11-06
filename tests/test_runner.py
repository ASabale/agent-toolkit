"""Isolated unit tests for lib.runner (CODING_STANDARDS.md §2.2)."""

import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

# Runner tests stay isolated from lib/catalog.py. Provide a stub only when
# that module is not importable yet so run_chain's lazy import can be patched.
try:
    import lib.catalog  # noqa: F401
except ModuleNotFoundError:
    _catalog_stub = types.ModuleType("lib.catalog")
    _catalog_stub.discover_catalog = lambda root_dir: {}
    sys.modules["lib.catalog"] = _catalog_stub

from lib.runner import (
    parse_cli_flags,
    run_chain,
    run_tool,
    validate_and_build_env,
)


def _item():
    return {
        "kind": "tool",
        "name": "demo.echo",
        "summary": "echo",
        "safety": "read-only",
        "args": [
            {
                "flag": "--name",
                "env_var": "TK_ARG_NAME",
                "required": True,
                "type": "string",
                "description": "Name",
                "default": None,
            },
            {
                "flag": "--limit",
                "env_var": "TK_ARG_LIMIT",
                "required": False,
                "type": "int",
                "description": "Maximum items (default: 20)",
                "default": "20",
            },
            {
                "flag": "--ratio",
                "env_var": "TK_ARG_RATIO",
                "required": False,
                "type": "float",
                "description": "Ratio",
                "default": None,
            },
            {
                "flag": "--verbose",
                "env_var": "TK_ARG_VERBOSE",
                "required": False,
                "type": "bool",
                "description": "Verbose",
                "default": None,
            },
        ],
        "output": "json",
        "example": "tk run demo.echo --name example --limit 10",
        "verified": "none",
        "path": "/tmp/demo-echo",
    }


def _write_script(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def _pid_alive(pid: int) -> bool:
    check = subprocess.run(
        ["ps", "-p", str(pid), "-o", "pid="],
        capture_output=True,
        text=True,
        check=False,
    )
    return check.returncode == 0 and bool(check.stdout.strip())


class ParseCliFlagsTests(unittest.TestCase):
    def test_dry_run_is_order_independent_and_not_a_flag(self):
        flags, dry_run, positional = parse_cli_flags(
            ["--limit", "5", "--dry-run", "--name=ada"]
        )
        self.assertTrue(dry_run)
        self.assertEqual(flags, {"--limit": "5", "--name": "ada"})
        self.assertEqual(positional, [])

    def test_dry_run_equals_form_and_bare_boolean(self):
        flags, dry_run, positional = parse_cli_flags(
            ["--dry-run=1", "--verbose", "--name", "-1"]
        )
        self.assertTrue(dry_run)
        self.assertEqual(flags, {"--verbose": "true", "--name": "-1"})
        self.assertEqual(positional, [])

    def test_dry_run_equals_false_is_not_a_dry_run(self):
        for value in ("0", "false", "FALSE", "no", "off"):
            flags, dry_run, positional = parse_cli_flags([f"--dry-run={value}", "--name", "ada"])
            self.assertFalse(dry_run, value)
            self.assertEqual(flags, {"--name": "ada"})
            self.assertEqual(positional, [])

    def test_positional_tokens_are_collected(self):
        flags, dry_run, positional = parse_cli_flags(["pos", "--name", "ada", "tail"])
        self.assertFalse(dry_run)
        self.assertEqual(flags, {"--name": "ada"})
        self.assertEqual(positional, ["pos", "tail"])

    def test_empty_argv(self):
        self.assertEqual(parse_cli_flags([]), ({}, False, []))

    def test_bool_flag_does_not_swallow_positional(self):
        item = {
            "args": [
                {"flag": "--verbose", "type": "bool"},
                {"flag": "--name", "type": "string"},
            ]
        }
        flags, dry_run, positional = parse_cli_flags(["--verbose", "leftover"], item)
        self.assertFalse(dry_run)
        self.assertEqual(flags, {"--verbose": "true"})
        self.assertEqual(positional, ["leftover"])

    def test_string_flag_accepts_hyphenated_value(self):
        item = {"args": [{"flag": "--query", "type": "string"}]}
        flags, dry_run, positional = parse_cli_flags(["--query", "--foo"], item)
        self.assertFalse(dry_run)
        self.assertEqual(flags, {"--query": "--foo"})
        self.assertEqual(positional, [])


class ValidateAndBuildEnvTests(unittest.TestCase):
    def test_rejects_positional_arguments(self):
        ok, env, err = validate_and_build_env(_item(), {"--name": "ada"}, ["oops"], False)
        self.assertFalse(ok)
        self.assertEqual(env, {})
        self.assertEqual(
            err,
            {
                "error": "positional_arguments_forbidden",
                "why": "positional arguments are forbidden: oops",
                "fix": "tk run demo.echo --name example --limit 10",
            },
        )

    def test_rejects_unknown_flags(self):
        ok, env, err = validate_and_build_env(
            _item(), {"--name": "ada", "--zoom": "1", "--qqqq": "x"}, [], False
        )
        self.assertFalse(ok)
        self.assertEqual(env, {})
        self.assertEqual(err["error"], "unknown_flag")
        self.assertEqual(err["why"], "unknown flags: --qqqq, --zoom")
        self.assertEqual(err["fix"], "tk run demo.echo --name example --limit 10")

    def test_unknown_flag_suggests_close_match_and_rewrites_fix(self):
        ok, env, err = validate_and_build_env(
            _item(), {"--nam": "ada lovelace", "--limt": "4"}, [], False
        )
        self.assertFalse(ok)
        self.assertEqual(env, {})
        self.assertEqual(err["error"], "unknown_flag")
        self.assertIn("--limt (did you mean --limit?)", err["why"])
        self.assertIn("--nam (did you mean --name?)", err["why"])
        self.assertEqual(
            err["fix"],
            "tk run demo.echo --name 'ada lovelace' --limit 4",
        )

    def test_single_unknown_suggests_the_one_missing_required_flag(self):
        ok, env, err = validate_and_build_env(_item(), {"--zzzz": "ada", "--limit": "3"}, [], False)
        self.assertFalse(ok)
        self.assertEqual(env, {})
        self.assertEqual(err["why"], "unknown flags: --zzzz")
        self.assertEqual(err["fix"], "tk run demo.echo --name example --limit 10")

    def test_missing_required_fix_keeps_supplied_flags_and_adds_a_runnable_value(self):
        ok, env, err = validate_and_build_env(_item(), {"--limit": "5"}, [], False)
        self.assertFalse(ok)
        self.assertEqual(env, {})
        self.assertEqual(err["error"], "missing_required")
        self.assertEqual(err["why"], "missing required flags: --name")
        self.assertEqual(err["fix"], "tk run demo.echo --limit 5 --name example")

    def test_rejects_invalid_types(self):
        ok, env, err = validate_and_build_env(
            _item(), {"--name": "ada", "--limit": "nope"}, [], False
        )
        self.assertFalse(ok)
        self.assertEqual(env, {})
        self.assertEqual(err["error"], "invalid_type")
        self.assertEqual(err["why"], "--limit expects int, got 'nope'")
        self.assertEqual(err["fix"], "tk run demo.echo --name ada --limit 10")

    def test_invalid_type_fix_keeps_other_flags_and_dry_run(self):
        ok, env, err = validate_and_build_env(
            _item(),
            {"--name": "ada lovelace", "--limit": "nope", "--verbose": "yes"},
            [],
            True,
        )
        self.assertFalse(ok)
        self.assertEqual(env, {})
        self.assertEqual(err["error"], "invalid_type")
        self.assertEqual(
            err["fix"],
            "tk run demo.echo --name 'ada lovelace' --limit 10 --verbose yes --dry-run",
        )

    def test_success_env_includes_defaults_and_dry_run_bit(self):
        ok, env, err = validate_and_build_env(
            _item(),
            {"--name": "ada", "--verbose": "YES", "--ratio": "1.5"},
            [],
            True,
        )
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(
            env,
            {
                "TK_DRY_RUN": "1",
                "TK_ARG_NAME": "ada",
                "TK_ARG_LIMIT": "20",
                "TK_ARG_RATIO": "1.5",
                "TK_ARG_VERBOSE": "true",
            },
        )

    def test_bool_false_and_quotes_values_with_spaces_in_fix(self):
        item = _item()
        item["args"][0]["required"] = True
        # name supplied with a space; count is a second required flag
        item["args"].append(
            {
                "flag": "--count",
                "env_var": "TK_ARG_COUNT",
                "required": True,
                "type": "int",
                "description": "Count",
                "default": None,
            }
        )
        ok, env, err = validate_and_build_env(
            item, {"--name": "ada lovelace", "--verbose": "0"}, [], False
        )
        self.assertFalse(ok)
        self.assertEqual(
            err["fix"],
            "tk run demo.echo --name 'ada lovelace' --verbose false --count 1",
        )
        self.assertEqual(env, {})


class RunToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env_patcher = patch.dict(
            os.environ,
            {"TK_NO_TELEMETRY": "", "TK_STATE_DIR": ""},
            clear=False,
        )
        self._env_patcher.start()

    def tearDown(self) -> None:
        self._env_patcher.stop()

    def test_compacts_json_stdout_and_injects_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = _write_script(
                root,
                "echo-tool",
                "#!/usr/bin/env python3\n"
                "import json, os\n"
                "json.dump({'name': os.environ['TK_ARG_NAME'], 'dry': os.environ['TK_DRY_RUN'], 'limit': int(os.environ['TK_ARG_LIMIT'])}, open(1, 'w'), indent=2)\n",
            )
            item = _item()
            item["path"] = str(script)
            code, out, err = run_tool(root, item, {"--name": "ada"}, dry_run=True)
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(out, '{"name":"ada","dry":"1","limit":20}')

    def test_validation_failure_is_json_on_stderr(self):
        item = _item()
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = run_tool(Path(tmp), item, {}, positional=["nope"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        payload = json.loads(err)
        self.assertEqual(payload["error"], "positional_arguments_forbidden")
        self.assertNotIn("\n", err)

    def test_nonzero_exit_wraps_stderr_and_hides_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = _write_script(
                root,
                "fail-tool",
                "#!/usr/bin/env python3\n"
                "import sys\n"
                "sys.stdout.write('not json')\n"
                "sys.stderr.write('boom')\n"
                "raise SystemExit(3)\n",
            )
            item = _item()
            item["path"] = str(script)
            code, out, err = run_tool(root, item, {"--name": "ada"})
        self.assertEqual(code, 3)
        self.assertEqual(out, "")
        payload = json.loads(err)
        self.assertEqual(payload["error"], "tool_failed")
        self.assertEqual(payload["why"], "boom")
        self.assertEqual(payload["fix"], item["example"])

    def test_passes_through_existing_json_error_on_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = _write_script(
                root,
                "json-err",
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                "json.dump({'error': 'nope', 'why': 'bad', 'fix': 'tk check'}, sys.stderr)\n"
                "raise SystemExit(2)\n",
            )
            item = _item()
            item["path"] = str(script)
            code, out, err = run_tool(root, item, {"--name": "ada"})
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertEqual(json.loads(err), {"error": "nope", "why": "bad", "fix": "tk check"})

    def test_tool_timeout_kills_descendants_and_logs_unless_dry_run(self):
        tracked_pids: list[int] = []

        def _reap_tracked() -> None:
            for pid in tracked_pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass

        self.addCleanup(_reap_tracked)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pid_file = root / "child.pid"
            script = _write_script(
                root,
                "slow-tool",
                "#!/bin/sh\n"
                "sleep 30 &\n"
                f"echo $! > '{pid_file}'\n"
                "wait\n"
                "printf '%s\\n' '{\"ok\":true}'\n",
            )
            item = _item()
            item["path"] = str(script)
            previous = os.environ.get("TK_TIMEOUT")
            os.environ["TK_TIMEOUT"] = "2"
            try:
                code, out, err = run_tool(root, item, {"--name": "ada"}, dry_run=True)
                self.assertEqual(code, 1)
                self.assertEqual(out, "")
                payload = json.loads(err)
                self.assertEqual(payload["error"], "tool_timeout")
                self.assertEqual(payload["fix"], "TK_TIMEOUT=4 tk run demo.echo --name ada")
                self.assertNotEqual(payload["fix"], item["example"])
                self.assertTrue(pid_file.is_file(), "descendant pid file was not written")
                child_pid = int(pid_file.read_text(encoding="utf-8").strip())
                tracked_pids.append(child_pid)
                self.assertFalse(_pid_alive(child_pid), f"descendant {child_pid} survived timeout")
                self.assertEqual(self._events(root), [])

                code, out, err = run_tool(root, item, {"--name": "ada"})
                self.assertEqual(code, 1)
                self.assertEqual(out, "")
                payload = json.loads(err)
                self.assertEqual(payload["error"], "tool_timeout")
                self.assertEqual(payload["fix"], "TK_TIMEOUT=4 tk run demo.echo --name ada")
                child_pid = int(pid_file.read_text(encoding="utf-8").strip())
                tracked_pids.append(child_pid)
                self.assertFalse(_pid_alive(child_pid), f"descendant {child_pid} survived timeout")
                events = self._events(root)
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0]["event"], "run_error")
                self.assertEqual(events[0]["name"], "demo.echo")
            finally:
                if previous is None:
                    os.environ.pop("TK_TIMEOUT", None)
                else:
                    os.environ["TK_TIMEOUT"] = previous

    def test_timeout_fix_is_runnable_with_larger_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = _write_script(
                root,
                "brief-slow",
                "#!/usr/bin/env python3\n"
                "import time\n"
                "time.sleep(1.2)\n"
                "print('{\"ok\":true}')\n",
            )
            item = _item()
            item["path"] = str(script)
            previous = os.environ.get("TK_TIMEOUT")
            os.environ["TK_TIMEOUT"] = "1"
            try:
                code, out, err = run_tool(root, item, {"--name": "ada"})
                self.assertEqual(code, 1)
                self.assertEqual(out, "")
                payload = json.loads(err)
                self.assertEqual(payload["error"], "tool_timeout")
                original = "tk run demo.echo --name ada"
                self.assertEqual(payload["fix"], "TK_TIMEOUT=2 " + original)
                self.assertNotEqual(payload["fix"], original)
                self.assertNotEqual(payload["fix"], item["example"])
                raised = payload["fix"].split(None, 1)[0]
                self.assertTrue(raised.startswith("TK_TIMEOUT="), payload["fix"])
                os.environ["TK_TIMEOUT"] = raised.split("=", 1)[1]
                code, out, err = run_tool(root, item, {"--name": "ada"})
                self.assertEqual(code, 0, err)
                self.assertEqual(out, '{"ok":true}')
            finally:
                if previous is None:
                    os.environ.pop("TK_TIMEOUT", None)
                else:
                    os.environ["TK_TIMEOUT"] = previous

    def test_malformed_timeout_and_max_output_use_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = _write_script(
                root,
                "ok-tool",
                "#!/usr/bin/env python3\nimport json\njson.dump({'ok': True}, open(1, 'w'))\n",
            )
            item = _item()
            item["path"] = str(script)
            saved = {key: os.environ.get(key) for key in ("TK_TIMEOUT", "TK_MAX_OUTPUT_BYTES")}
            os.environ["TK_TIMEOUT"] = ""
            os.environ["TK_MAX_OUTPUT_BYTES"] = "abc"
            try:
                code, out, err = run_tool(root, item, {"--name": "ada"})
            finally:
                for key, value in saved.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
        self.assertEqual(code, 0)
        self.assertEqual(out, '{"ok":true}')
        self.assertEqual(err, "")
        self.assertNotIn("internal_error", err)

    def test_success_requires_json_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = _write_script(
                root,
                "text-tool",
                "#!/bin/sh\nprintf 'hello'\n",
            )
            item = _item()
            item["path"] = str(script)
            code, out, err = run_tool(root, item, {"--name": "ada"})
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(
            json.loads(err),
            {"error": "invalid_output", "why": "stdout is not valid JSON", "fix": "tk check"},
        )

    def test_forwards_stdin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = _write_script(
                root,
                "stdin-tool",
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                "raw = sys.stdin.read()\n"
                "json.dump({'stdin': json.loads(raw)}, sys.stdout)\n",
            )
            item = _item()
            item["path"] = str(script)
            code, out, err = run_tool(
                root, item, {"--name": "ada"}, stdin_data='{"n": 1}'
            )
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertEqual(out, '{"stdin":{"n":1}}')

    def _events(self, root: Path) -> list[dict]:
        path = root / "state" / "events.jsonl"
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def test_real_run_logs_ok_and_error_and_dry_run_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = _write_script(
                root,
                "echo-tool",
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "if os.environ.get('TK_ARG_NAME') == 'bad':\n"
                "    json.dump({'error': 'nope', 'why': 'refused', 'fix': 'tk check'}, sys.stderr)\n"
                "    raise SystemExit(2)\n"
                "json.dump({'ok': True}, sys.stdout)\n",
            )
            item = _item()
            item["path"] = str(script)
            code, _out, err = run_tool(root, item, {"--name": "ada"}, dry_run=True)
            self.assertEqual(code, 0, err)
            self.assertEqual(self._events(root), [])

            code, out, err = run_tool(root, item, {"--name": "ada"})
            self.assertEqual(code, 0, err)
            self.assertEqual(out, '{"ok":true}')
            events = self._events(root)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["event"], "run_ok")
            self.assertEqual(events[0]["name"], "demo.echo")
            self.assertEqual(events[0]["kind"], "tool")

            code, _out, err = run_tool(root, item, {"--name": "bad"})
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(err)["why"], "refused")
            events = self._events(root)
            self.assertEqual(events[1]["event"], "run_error")
            self.assertEqual(events[1]["name"], "demo.echo")
            self.assertEqual(events[1]["kind"], "tool")
            self.assertEqual(events[1]["why"], "refused")

    def test_truncated_int_adds_copy_pasteable_next_with_larger_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = _write_script(
                root,
                "trunc-tool",
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                "json.dump({'count': 3, 'truncated': 5, 'items': [1, 2, 3]}, sys.stdout)\n",
            )
            item = _item()
            item["path"] = str(script)
            code, out, err = run_tool(root, item, {"--name": "ada", "--limit": "3"})
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assertEqual(payload["truncated"], 5)
        self.assertEqual(payload["next"], "tk run demo.echo --name ada --limit 6")
        self.assertEqual(
            out,
            '{"count":3,"truncated":5,"items":[1,2,3],"next":"tk run demo.echo --name ada --limit 6"}',
        )

    def test_truncated_zero_and_bool_leave_stdout_byte_identical(self):
        cases = (
            ("zero-tool", "{'count': 1, 'truncated': 0, 'items': [1]}", '{"count":1,"truncated":0,"items":[1]}'),
            ("bool-tool", "{'count': 1, 'truncated': True, 'items': [1]}", '{"count":1,"truncated":true,"items":[1]}'),
        )
        for name, dumped, expected in cases:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                script = _write_script(
                    root,
                    name,
                    "#!/usr/bin/env python3\n"
                    "import json, sys\n"
                    f"json.dump({dumped}, sys.stdout)\n",
                )
                item = _item()
                item["path"] = str(script)
                code, out, err = run_tool(root, item, {"--name": "ada", "--limit": "3"})
            self.assertEqual(code, 0, err)
            self.assertEqual(err, "")
            self.assertNotIn("next", json.loads(out))
            self.assertEqual(out, expected)

    def test_truncated_without_limit_arg_leaves_stdout_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = _write_script(
                root,
                "no-limit",
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                "json.dump({'count': 1, 'truncated': 4, 'items': [1]}, sys.stdout)\n",
            )
            item = _item()
            item["args"] = [arg for arg in item["args"] if arg["flag"] != "--limit"]
            item["path"] = str(script)
            code, out, err = run_tool(root, item, {"--name": "ada"})
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")
        self.assertEqual(out, '{"count":1,"truncated":4,"items":[1]}')

    def test_output_over_byte_ceiling_is_output_too_large(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = _write_script(
                root,
                "big-tool",
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                "json.dump({'blob': 'x' * 40}, sys.stdout)\n",
            )
            item = _item()
            item["path"] = str(script)
            previous = os.environ.get("TK_MAX_OUTPUT_BYTES")
            os.environ["TK_MAX_OUTPUT_BYTES"] = "16"
            try:
                code, out, err = run_tool(root, item, {"--name": "ada"}, dry_run=True)
                self.assertEqual(code, 1)
                self.assertEqual(out, "")
                payload = json.loads(err)
                self.assertEqual(payload["error"], "output_too_large")
                self.assertIn("exceeds TK_MAX_OUTPUT_BYTES (16)", payload["why"])
                self.assertTrue(payload["fix"].startswith("tk run "))
                self.assertEqual(
                    payload["fix"],
                    "tk run demo.echo --name ada --limit 10",
                )
                self.assertEqual(self._events(root), [])

                code, out, err = run_tool(root, item, {"--name": "ada"})
                self.assertEqual(code, 1)
                self.assertEqual(out, "")
                payload = json.loads(err)
                size = int(payload["why"].split()[1])
                self.assertGreater(size, 16)
                events = self._events(root)
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0]["event"], "run_error")
                self.assertEqual(events[0]["why"], payload["why"])
            finally:
                if previous is None:
                    os.environ.pop("TK_MAX_OUTPUT_BYTES", None)
                else:
                    os.environ["TK_MAX_OUTPUT_BYTES"] = previous

    def test_output_too_large_without_limit_pipes_to_json_pick(self):
        root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env["TK_MAX_OUTPUT_BYTES"] = "16"
        env["TK_NO_TELEMETRY"] = "1"
        env["PATH"] = str(root) + os.pathsep + env.get("PATH", "")
        failed = subprocess.run(
            [sys.executable, str(root / "tk"), "run", "env.check"],
            capture_output=True,
            text=True,
            cwd=str(root),
            env=env,
            check=False,
        )
        self.assertEqual(failed.returncode, 1, failed.stderr)
        payload = json.loads(failed.stderr)
        self.assertEqual(payload["error"], "output_too_large")
        fix = payload["fix"]
        self.assertTrue(fix.startswith("TK_MAX_OUTPUT_BYTES="), fix)
        self.assertIn("tk run env.check", fix)
        self.assertIn("| tk run json.pick --keys ", fix)
        self.assertNotIn("ok,binaries,variables,missing_bins,missing_vars", fix)
        healed = subprocess.run(
            fix,
            shell=True,
            capture_output=True,
            text=True,
            cwd=str(root),
            env=env,
            check=False,
        )
        self.assertEqual(healed.returncode, 0, healed.stderr + healed.stdout)
        reduced = json.loads(healed.stdout)
        self.assertIsInstance(reduced, dict)
        self.assertLessEqual(len(json.dumps(reduced, separators=(",", ":")).encode()), 16)


    def test_failed_run_feedback_is_local_and_redacted(self):
        token = "ghp_" + ("a" * 36)
        home = str(Path.home())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = _write_script(
                root,
                "fail.sh",
                "#!/bin/sh\n"
                f"printf '%s\\n' '{token} {home}/secret' >&2\n"
                "exit 1\n",
            )
            item = _item()
            item["path"] = str(script)
            code, out, err = run_tool(root, item, {"--name": "ada"})
            self.assertEqual(code, 1)
            self.assertEqual(out, "")
            self.assertNotIn(token, err)
            self.assertIn(home, err)
            feedback = root / "state" / "feedback.jsonl"
            row = json.loads(feedback.read_text(encoding="utf-8"))
            self.assertEqual(row["name"], "demo.echo")
            self.assertEqual(row["exit"], 1)
            self.assertNotIn(token, row["stderr"])
            self.assertNotIn(home, row["stderr"])
            self.assertIn("***", row["stderr"])
            self.assertIn("~/", row["stderr"])

            script.write_text("#!/bin/sh\nprintf '%s\\n' '{\"ok\":true}'\n", encoding="utf-8")
            code, _out, err = run_tool(root, item, {"--name": "ada"})
            self.assertEqual(code, 0, err)
            self.assertEqual(len(feedback.read_text(encoding="utf-8").splitlines()), 1)


class RunChainTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env_patcher = patch.dict(
            os.environ,
            {"TK_NO_TELEMETRY": "", "TK_STATE_DIR": ""},
            clear=False,
        )
        self._env_patcher.start()

    def tearDown(self) -> None:
        self._env_patcher.stop()

    def _tools(self, root: Path):
        first = _write_script(
            root,
            "first",
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "json.dump({'id': os.environ['TK_ARG_ID'], 'n': 2}, sys.stdout)\n",
        )
        second = _write_script(
            root,
            "second",
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "seen = json.loads(sys.stdin.read())\n"
            "json.dump({'id': os.environ['TK_ARG_ID'], 'prev_n': seen['n'], 'label': os.environ['TK_ARG_LABEL']}, sys.stdout)\n",
        )
        third = _write_script(
            root,
            "third",
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "json.dump({'from_step0': os.environ['TK_ARG_FROM'], 'via': os.environ['TK_ARG_VIA']}, sys.stdout)\n",
        )
        boom = _write_script(
            root,
            "boom",
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "sys.stderr.write('step failed')\n"
            "raise SystemExit(4)\n",
        )
        marker = root / "marker"
        later = _write_script(
            root,
            "later",
            "#!/usr/bin/env python3\n"
            f"open({str(marker)!r}, 'w').write('ran')\n"
            "print('{{}}')\n",
        )
        catalog = {
            "demo.first": {
                "name": "demo.first",
                "example": "tk run demo.first --id x",
                "path": str(first),
                "args": [
                    {
                        "flag": "--id",
                        "env_var": "TK_ARG_ID",
                        "required": True,
                        "type": "string",
                        "description": "id",
                        "default": None,
                    }
                ],
            },
            "demo.second": {
                "name": "demo.second",
                "example": "tk run demo.second --id x --label y",
                "path": str(second),
                "args": [
                    {
                        "flag": "--id",
                        "env_var": "TK_ARG_ID",
                        "required": True,
                        "type": "string",
                        "description": "id",
                        "default": None,
                    },
                    {
                        "flag": "--label",
                        "env_var": "TK_ARG_LABEL",
                        "required": True,
                        "type": "string",
                        "description": "label",
                        "default": None,
                    },
                ],
            },
            "demo.third": {
                "name": "demo.third",
                "example": "tk run demo.third --from x --via y",
                "path": str(third),
                "args": [
                    {
                        "flag": "--from",
                        "env_var": "TK_ARG_FROM",
                        "required": True,
                        "type": "string",
                        "description": "from",
                        "default": None,
                    },
                    {
                        "flag": "--via",
                        "env_var": "TK_ARG_VIA",
                        "required": True,
                        "type": "string",
                        "description": "via",
                        "default": None,
                    },
                ],
            },
            "demo.boom": {
                "name": "demo.boom",
                "example": "tk run demo.boom",
                "path": str(boom),
                "args": [],
            },
            "demo.later": {
                "name": "demo.later",
                "example": "tk run demo.later",
                "path": str(later),
                "args": [],
            },
        }
        return catalog, marker

    def _chain(self):
        return {
            "kind": "chain",
            "name": "demo.pipe",
            "example": "tk run demo.pipe --id example",
            "args": [
                {
                    "flag": "--id",
                    "env_var": "TK_ARG_ID",
                    "required": True,
                    "type": "string",
                    "description": "id",
                    "default": None,
                },
                {
                    "flag": "--label",
                    "env_var": "TK_ARG_LABEL",
                    "required": False,
                    "type": "string",
                    "description": "label (default: item)",
                    "default": "item",
                },
            ],
            "steps": [
                {"tool": "demo.first", "args": {"--id": "$input.id"}},
                {
                    "tool": "demo.second",
                    "args": {"--id": "$prev.id", "--label": "$input.label"},
                },
                {
                    "tool": "demo.third",
                    "args": {"--from": "$step[0].id", "--via": "$prev.prev_n"},
                },
            ],
        }

    def test_resolves_input_prev_and_step_and_pipes_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog, _marker = self._tools(root)
            with patch("lib.catalog.discover_catalog", return_value=catalog):
                code, out, err = run_chain(root, self._chain(), {"--id": "a9"})
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")
        self.assertEqual(out, '{"from_step0":"a9","via":"2"}')

    def test_halts_on_first_step_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog, marker = self._tools(root)
            chain = self._chain()
            chain["steps"] = [
                {"tool": "demo.boom", "args": {}},
                {"tool": "demo.later", "args": {}},
            ]
            with patch("lib.catalog.discover_catalog", return_value=catalog):
                code, out, err = run_chain(root, chain, {"--id": "a9"})
        self.assertEqual(code, 4)
        self.assertEqual(out, "")
        payload = json.loads(err)
        self.assertEqual(payload["error"], "tool_failed")
        self.assertEqual(
            payload["why"],
            "chain demo.pipe stopped at step 1/2 (demo.boom): step failed",
        )
        self.assertEqual(payload["fix"], "tk run demo.boom")
        self.assertFalse(marker.exists())

    def test_second_step_failure_names_step_and_skips_the_rest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog, marker = self._tools(root)
            chain = self._chain()
            chain["steps"] = [
                {"tool": "demo.first", "args": {"--id": "$input.id"}},
                {"tool": "demo.boom", "args": {}},
                {"tool": "demo.later", "args": {}},
            ]
            with patch("lib.catalog.discover_catalog", return_value=catalog):
                code, out, err = run_chain(root, chain, {"--id": "a9"})
        self.assertEqual(code, 4)
        payload = json.loads(err)
        self.assertIn(
            "chain demo.pipe stopped at step 2/3 (demo.boom):",
            payload["why"],
        )
        self.assertEqual(payload["fix"], "tk run demo.boom")
        self.assertFalse(marker.exists())

    def test_chain_flag_validation_and_unknown_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chain = self._chain()
            code, out, err = run_chain(root, chain, {}, positional=["x"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(err)["error"], "positional_arguments_forbidden")

        chain["steps"] = [{"tool": "missing.tool", "args": {}}]
        with patch("lib.catalog.discover_catalog", return_value={}):
            code, out, err = run_chain(root, chain, {"--id": "a9"})
        self.assertEqual(code, 1)
        self.assertEqual(
            json.loads(err),
            {
                "error": "unknown_tool",
                "why": "unknown tool: missing.tool",
                "fix": "tk run demo.pipe --id example",
            },
        )

    def test_whole_object_prev_and_step_refs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog, _marker = self._tools(root)
            chain = self._chain()
            chain["steps"] = [
                {"tool": "demo.first", "args": {"--id": "$input.id"}},
                {"tool": "demo.second", "args": {"--id": "$prev", "--label": "$step[0]"}},
            ]
            with patch("lib.catalog.discover_catalog", return_value=catalog):
                code, out, err = run_chain(root, chain, {"--id": "a9"})
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        self.assertEqual(json.loads(payload["id"]), {"id": "a9", "n": 2})
        self.assertEqual(json.loads(payload["label"]), {"id": "a9", "n": 2})

    def test_dry_run_falls_back_when_synthetic_payload_omits_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = _write_script(
                root,
                "dry",
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "if os.environ.get('TK_DRY_RUN') == '1':\n"
                "    json.dump({'dry_run': True}, sys.stdout)\n"
                "else:\n"
                "    json.dump({'id': os.environ['TK_ARG_ID'], 'n': 2}, sys.stdout)\n",
            )
            sink = _write_script(
                root,
                "sink",
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "json.dump({'n': os.environ['TK_ARG_N'], 'on': os.environ['TK_ARG_ON'], 'name': os.environ['TK_ARG_NAME']}, sys.stdout)\n",
            )
            catalog = {
                "demo.dry": {
                    "name": "demo.dry",
                    "example": "tk run demo.dry --id x",
                    "path": str(script),
                    "args": [{
                        "flag": "--id",
                        "env_var": "TK_ARG_ID",
                        "required": True,
                        "type": "string",
                        "description": "id",
                        "default": None,
                    }],
                },
                "demo.sink": {
                    "name": "demo.sink",
                    "example": "tk run demo.sink --n 1 --on true --name example",
                    "path": str(sink),
                    "args": [
                        {"flag": "--n", "env_var": "TK_ARG_N", "required": True, "type": "int", "description": "n", "default": None},
                        {"flag": "--on", "env_var": "TK_ARG_ON", "required": True, "type": "bool", "description": "on", "default": None},
                        {"flag": "--name", "env_var": "TK_ARG_NAME", "required": True, "type": "string", "description": "name", "default": None},
                    ],
                },
            }
            chain = {
                "kind": "chain",
                "name": "demo.drypipe",
                "example": "tk run demo.drypipe --id example",
                "args": [{
                    "flag": "--id",
                    "env_var": "TK_ARG_ID",
                    "required": True,
                    "type": "string",
                    "description": "id",
                    "default": None,
                }],
                "steps": [
                    {"tool": "demo.dry", "args": {"--id": "$input.id"}},
                    {"tool": "demo.sink", "args": {
                        "--n": "$prev.n",
                        "--on": "$step[0].on",
                        "--name": "$prev.name",
                    }},
                ],
            }
            with patch("lib.catalog.discover_catalog", return_value=catalog):
                code, out, err = run_chain(root, chain, {"--id": "a9"}, dry_run=True)
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out), {"n": "1", "on": "true", "name": "example"})

            with patch("lib.catalog.discover_catalog", return_value=catalog):
                code, _out, err = run_chain(root, chain, {"--id": "a9"}, dry_run=False)
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(err)["error"], "unresolved_reference")

    def test_unresolved_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog, _marker = self._tools(root)
            chain = self._chain()
            chain["steps"] = [
                {"tool": "demo.first", "args": {"--id": "$input.missing"}},
            ]
            with patch("lib.catalog.discover_catalog", return_value=catalog):
                code, out, err = run_chain(root, chain, {"--id": "a9"})
        self.assertEqual(code, 1)
        payload = json.loads(err)
        self.assertEqual(payload["error"], "unresolved_reference")
        self.assertIn("$input.missing", payload["why"])

    def test_chain_logs_its_own_outcome_and_dry_run_skips_run_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog, _marker = self._tools(root)
            chain = self._chain()
            with patch("lib.catalog.discover_catalog", return_value=catalog):
                code, out, err = run_chain(root, chain, {"--id": "a9"}, dry_run=True)
            self.assertEqual(code, 0, err)
            self.assertEqual(out, '{"from_step0":"a9","via":"2"}')
            path = root / "state" / "events.jsonl"
            self.assertFalse(path.exists())

            with patch("lib.catalog.discover_catalog", return_value=catalog):
                code, _out, err = run_chain(root, chain, {"--id": "a9"})
            self.assertEqual(code, 0, err)
            events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            names = [(event["event"], event["name"]) for event in events]
            self.assertIn(("run_ok", "demo.first"), names)
            self.assertIn(("run_ok", "demo.pipe"), names)
            self.assertEqual(events[-1]["kind"], "chain")


if __name__ == "__main__":
    unittest.main()
