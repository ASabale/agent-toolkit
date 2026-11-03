"""Isolated unit tests for lib.runner (CODING_STANDARDS.md §2.2)."""

import json
import stat
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

    def test_positional_tokens_are_collected(self):
        flags, dry_run, positional = parse_cli_flags(["pos", "--name", "ada", "tail"])
        self.assertFalse(dry_run)
        self.assertEqual(flags, {"--name": "ada"})
        self.assertEqual(positional, ["pos", "tail"])

    def test_empty_argv(self):
        self.assertEqual(parse_cli_flags([]), ({}, False, []))


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
            _item(), {"--name": "ada", "--zoom": "1", "--extra": "x"}, [], False
        )
        self.assertFalse(ok)
        self.assertEqual(env, {})
        self.assertEqual(err["error"], "unknown_flag")
        self.assertEqual(err["why"], "unknown flags: --extra, --zoom")
        self.assertEqual(err["fix"], "tk run demo.echo --name example --limit 10")

    def test_missing_required_fix_keeps_supplied_flags_and_appends_placeholders(self):
        ok, env, err = validate_and_build_env(_item(), {"--limit": "5"}, [], False)
        self.assertFalse(ok)
        self.assertEqual(env, {})
        self.assertEqual(err["error"], "missing_required")
        self.assertEqual(err["why"], "missing required flags: --name")
        self.assertEqual(err["fix"], "tk run demo.echo --limit 5 --name <value>")

    def test_rejects_invalid_types(self):
        ok, env, err = validate_and_build_env(
            _item(), {"--name": "ada", "--limit": "nope"}, [], False
        )
        self.assertFalse(ok)
        self.assertEqual(env, {})
        self.assertEqual(err["error"], "invalid_type")
        self.assertEqual(err["why"], "--limit expects int, got 'nope'")
        self.assertEqual(err["fix"], "tk run demo.echo --name example --limit 10")

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
            "tk run demo.echo --name 'ada lovelace' --verbose false --count <value>",
        )
        self.assertEqual(env, {})


class RunToolTests(unittest.TestCase):
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


class RunChainTests(unittest.TestCase):
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
        self.assertEqual(json.loads(err)["error"], "tool_failed")
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
