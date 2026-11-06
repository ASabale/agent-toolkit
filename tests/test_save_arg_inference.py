"""tk save must not infer flags from TK_ARG_ inside string literals."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.catalog import discover_catalog  # noqa: E402
from lib.evolver import save_tool, write_state_json  # noqa: E402
from lib.runner import _sha256_file, run_tool  # noqa: E402


def _hash_confirm(root: Path, name: str) -> None:
    item = discover_catalog(root)[name]
    write_state_json(
        root,
        "policy.json",
        {
            "version": 1,
            "classes": {"read-only": "allow", "mutating": "confirm", "destructive": "deny"},
            "rules": [{"rank": "hash", "sha256": _sha256_file(item["path"]), "decision": "confirm"}],
        },
    )

_REPRO_CMD = 'echo "{\\"hint\\":\\"tools read TK_ARG_FOO\\"}"'


class SaveArgInferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.root = base / "toolkit"
        self.state = base / "state"
        self.root.mkdir()
        self.state.mkdir()
        (self.root / "tools").mkdir()
        (self.root / "chains").mkdir()
        self._env_patcher = patch.dict(
            os.environ,
            {"TK_STATE_DIR": str(self.state), "TK_NO_TELEMETRY": "1"},
            clear=False,
        )
        self._env_patcher.start()

    def tearDown(self) -> None:
        self._env_patcher.stop()
        self._tmp.cleanup()

    def _saved_text(self, out: str) -> str:
        return Path(json.loads(out)["path"]).read_text(encoding="utf-8")

    def _header_block(self, text: str) -> str:
        return text.split("set -euo pipefail", 1)[0] if "set -euo pipefail" in text else text

    def test_string_literal_tk_arg_is_not_inferred(self) -> None:
        code, out, err = save_tool(
            self.root,
            "demo.note",
            "Echo a hint that mentions TK_ARG_FOO",
            from_cmd=_REPRO_CMD,
        )
        self.assertEqual(code, 0, err)
        text = self._saved_text(out)
        header = self._header_block(text)
        self.assertNotIn("--foo", header)
        self.assertNotIn("@tk-arg", header)

        item = discover_catalog(self.root)["demo.note"]
        _hash_confirm(self.root, "demo.note")
        ran, stdout, stderr = run_tool(self.root, item, {}, [])
        self.assertEqual(ran, 0, stderr)
        self.assertEqual(json.loads(stdout)["hint"], "tools read TK_ARG_FOO")

    def test_dollar_tk_arg_is_required(self) -> None:
        code, out, err = save_tool(
            self.root,
            "demo.need",
            "Echo a required foo value",
            from_cmd='printf \'%s\\n\' "{\\"foo\\":\\"$TK_ARG_FOO\\"}"',
        )
        self.assertEqual(code, 0, err)
        text = self._saved_text(out)
        self.assertIn("# @tk-arg: --foo | required | string | Parameter foo", text)
        self.assertIn("tk run demo.need --foo example", text)

        item = discover_catalog(self.root)["demo.need"]
        _hash_confirm(self.root, "demo.need")
        missing, _, stderr = run_tool(self.root, item, {}, [])
        self.assertNotEqual(missing, 0)
        self.assertEqual(json.loads(stderr)["error"], "missing_required")

        ran, stdout, stderr = run_tool(self.root, item, {"--foo": "bar"}, [])
        self.assertEqual(ran, 0, stderr)
        self.assertEqual(json.loads(stdout)["foo"], "bar")

    def test_braced_default_tk_arg_is_optional(self) -> None:
        code, out, err = save_tool(
            self.root,
            "demo.opt",
            "Echo an optional foo value",
            from_cmd='printf \'%s\\n\' "{\\"foo\\":\\"${TK_ARG_FOO:-x}\\"}"',
        )
        self.assertEqual(code, 0, err)
        text = self._saved_text(out)
        self.assertIn(
            "# @tk-arg: --foo | optional | string | Parameter foo (default: x)",
            text,
        )
        self.assertIn("tk run demo.opt", text)
        self.assertNotIn("--foo example", text.split("# @tk-example:", 1)[1].splitlines()[0])

        item = discover_catalog(self.root)["demo.opt"]
        _hash_confirm(self.root, "demo.opt")
        ran, stdout, stderr = run_tool(self.root, item, {}, [])
        self.assertEqual(ran, 0, stderr)
        self.assertEqual(json.loads(stdout)["foo"], "x")

    def test_python_environ_tk_arg_is_inferred(self) -> None:
        source = self.root / "pyenv.py"
        source.write_text(
            "#!/usr/bin/env python3\n"
            "# @tk-name: demo.pyenv\n"
            "# @tk-summary: Read FOO from the process environment\n"
            "# @tk-safety: read-only\n"
            "# @tk-output: json | Compact JSON result\n"
            "# @tk-example: tk run demo.pyenv\n"
            "# @tk-verified: none\n"
            "import json\n"
            "import os\n"
            "if os.environ.get('TK_DRY_RUN') == '1':\n"
            "    print(json.dumps({'dry_run': True, 'foo': os.environ['TK_ARG_FOO']}))\n"
            "else:\n"
            "    print(json.dumps({'foo': os.environ['TK_ARG_FOO']}))\n",
            encoding="utf-8",
        )
        code, out, err = save_tool(
            self.root,
            "demo.pyenv",
            "Read FOO from the process environment",
            file_path=str(source),
        )
        self.assertEqual(code, 0, err)
        text = self._saved_text(out)
        self.assertIn("# @tk-arg: --foo | required | string | Parameter foo", text)
        self.assertIn("tk run demo.pyenv --foo example", text)

        item = discover_catalog(self.root)["demo.pyenv"]
        _hash_confirm(self.root, "demo.pyenv")
        ran, stdout, stderr = run_tool(self.root, item, {"--foo": "bar"}, [])
        self.assertEqual(ran, 0, stderr)
        self.assertEqual(json.loads(stdout)["foo"], "bar")

    def test_cli_repro_declares_no_foo_and_run_exits_zero(self) -> None:
        toolkit = Path(self._tmp.name) / "cli-toolkit"
        shutil.copytree(
            ROOT,
            toolkit,
            ignore=shutil.ignore_patterns(
                "__pycache__",
                "*.pyc",
                ".git",
                "state",
                "tools",
                "chains",
            ),
        )
        (toolkit / "tools").mkdir()
        (toolkit / "chains").mkdir()
        tk = toolkit / "tk"
        tk.chmod(tk.stat().st_mode | 0o755)
        env = os.environ.copy()
        env["TK_STATE_DIR"] = str(self.state)
        env["TK_NO_TELEMETRY"] = "1"

        saved = subprocess.run(
            [
                str(tk),
                "save",
                "demo.note",
                "--summary",
                "Echo a hint that mentions TK_ARG_FOO",
                "--from-cmd",
                _REPRO_CMD,
            ],
            capture_output=True,
            text=True,
            cwd=toolkit,
            env=env,
        )
        self.assertEqual(saved.returncode, 0, saved.stderr)
        tool = toolkit / "tools" / "demo" / "note"
        header = self._header_block(tool.read_text(encoding="utf-8"))
        self.assertNotIn("--foo", header)
        self.assertNotIn("@tk-arg", header)
        _hash_confirm(toolkit, "demo.note")

        ran = subprocess.run(
            [str(tk), "run", "demo.note"],
            capture_output=True,
            text=True,
            cwd=toolkit,
            env=env,
        )
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertEqual(json.loads(ran.stdout)["hint"], "tools read TK_ARG_FOO")


if __name__ == "__main__":
    unittest.main()
