"""Headerless --file scripts keep their interpreter instead of becoming bash."""

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

from lib.catalog import check_item, discover_catalog  # noqa: E402
from lib.evolver import save_tool  # noqa: E402
from lib.runner import run_tool  # noqa: E402


class SaveFileInterpreterTests(unittest.TestCase):
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

    def _write(self, name: str, text: str) -> Path:
        path = Path(self._tmp.name) / name
        path.write_text(text, encoding="utf-8")
        return path

    def _saved_text(self, out: str) -> str:
        return Path(json.loads(out)["path"]).read_text(encoding="utf-8")

    def test_headerless_python_save_runs_without_bash_wrap(self) -> None:
        source = self._write(
            "s.py",
            "#!/usr/bin/env python3\nprint('{}')\n",
        )
        code, out, err = save_tool(
            self.root,
            "demo.py",
            "Print empty JSON",
            file_path=str(source),
        )
        self.assertEqual(code, 0, err)
        self.assertNotIn("bash syntax", err.lower())
        self.assertNotIn("syntax error", err.lower())
        payload = json.loads(out)
        self.assertTrue(payload["ok"])
        text = self._saved_text(out)
        self.assertTrue(text.startswith("#!/usr/bin/env python3"))
        self.assertIn("# @tk-name: demo.py", text)
        self.assertIn("TK_DRY_RUN", text)
        self.assertNotIn("set -euo pipefail", text)
        self.assertNotIn("#!/usr/bin/env bash", text)

        checked = check_item(self.root, "demo.py")
        self.assertTrue(checked["ok"], checked)

        item = discover_catalog(self.root)["demo.py"]
        ran, stdout, stderr = run_tool(self.root, item, {}, [])
        self.assertEqual(ran, 0, stderr)
        self.assertEqual(json.loads(stdout), {})

    def test_headerless_python_mutating_prints_plan_and_skips_body(self) -> None:
        target = Path(self._tmp.name) / "created.txt"
        source = self._write(
            "touch.py",
            "#!/usr/bin/env python3\n"
            "from pathlib import Path\n"
            "import os\n"
            "Path(os.environ['TK_ARG_PATH']).write_text('wrote')\n"
            "print('{}')\n",
        )
        code, out, err = save_tool(
            self.root,
            "demo.touch",
            "Write a path then print empty JSON",
            safety="mutating",
            file_path=str(source),
        )
        self.assertEqual(code, 0, err)
        text = self._saved_text(out)
        self.assertIn("TK_DRY_RUN", text)
        self.assertIn('"plan"', text)

        checked = check_item(self.root, "demo.touch")
        self.assertTrue(checked["ok"], checked)
        self.assertFalse(target.exists())

        item = discover_catalog(self.root)["demo.touch"]
        ran, stdout, stderr = run_tool(
            self.root, item, {"--path": str(target)}, [], dry_run=True
        )
        self.assertEqual(ran, 0, stderr)
        payload = json.loads(stdout)
        self.assertIs(payload["dry_run"], True)
        self.assertIsInstance(payload.get("plan"), list)
        self.assertTrue(payload["plan"])
        self.assertFalse(target.exists())

        live, live_out, live_err = run_tool(
            self.root, item, {"--path": str(target)}, [], confirmed=True
        )
        self.assertEqual(live, 0, live_err)
        self.assertEqual(json.loads(live_out), {})
        self.assertEqual(target.read_text(encoding="utf-8"), "wrote")

    def test_headerless_python_keeps_future_import_legal(self) -> None:
        source = self._write(
            "future.py",
            "#!/usr/bin/env python3\n"
            "from __future__ import annotations\n"
            "print('{}')\n",
        )
        code, out, err = save_tool(
            self.root,
            "demo.future",
            "Print empty JSON after a future import",
            file_path=str(source),
        )
        self.assertEqual(code, 0, err)
        text = self._saved_text(out)
        future_at = text.index("from __future__ import annotations")
        guard_at = text.index("TK_DRY_RUN")
        self.assertLess(future_at, guard_at)
        item = discover_catalog(self.root)["demo.future"]
        ran, stdout, stderr = run_tool(self.root, item, {}, [])
        self.assertEqual(ran, 0, stderr)
        self.assertEqual(json.loads(stdout), {})

    def test_headerless_bash_and_sh_still_wrap(self) -> None:
        bash_src = self._write(
            "s.sh",
            "#!/usr/bin/env bash\nprintf '%s\\n' '{}'\n",
        )
        code, out, err = save_tool(
            self.root,
            "demo.bash",
            "Print empty JSON from bash",
            file_path=str(bash_src),
        )
        self.assertEqual(code, 0, err)
        bash_text = self._saved_text(out)
        self.assertTrue(bash_text.startswith("#!/usr/bin/env bash"))
        self.assertIn("set -euo pipefail", bash_text)
        item = discover_catalog(self.root)["demo.bash"]
        ran, stdout, stderr = run_tool(self.root, item, {}, [])
        self.assertEqual(ran, 0, stderr)
        self.assertEqual(json.loads(stdout), {})

        sh_src = self._write(
            "s-plain.sh",
            "#!/bin/sh\nprintf '%s\\n' '{}'\n",
        )
        code, out, err = save_tool(
            self.root,
            "demo.sh",
            "Print empty JSON from sh",
            file_path=str(sh_src),
        )
        self.assertEqual(code, 0, err)
        sh_text = self._saved_text(out)
        self.assertTrue(sh_text.startswith("#!/usr/bin/env bash"))
        self.assertIn("set -euo pipefail", sh_text)

    def test_headerless_no_shebang_and_from_cmd_still_wrap(self) -> None:
        source = self._write("plain.sh", "printf '%s\\n' '{}'\n")
        code, out, err = save_tool(
            self.root,
            "demo.plain",
            "Print empty JSON without a shebang",
            file_path=str(source),
        )
        self.assertEqual(code, 0, err)
        text = self._saved_text(out)
        self.assertTrue(text.startswith("#!/usr/bin/env bash"))
        self.assertIn("set -euo pipefail", text)
        item = discover_catalog(self.root)["demo.plain"]
        ran, stdout, stderr = run_tool(self.root, item, {}, [])
        self.assertEqual(ran, 0, stderr)
        self.assertEqual(json.loads(stdout), {})

        code, out, err = save_tool(
            self.root,
            "demo.cmd",
            "Print empty JSON from a command",
            from_cmd="printf '%s\\n' '{}'",
        )
        self.assertEqual(code, 0, err)
        cmd_text = self._saved_text(out)
        self.assertTrue(cmd_text.startswith("#!/usr/bin/env bash"))
        self.assertIn("set -euo pipefail", cmd_text)
        self.assertIn("printf '%s\\n' '{}'", cmd_text)

    def test_unsupported_shebang_is_not_a_bash_syntax_error(self) -> None:
        source = self._write(
            "s.js",
            "#!/usr/bin/env node\nconsole.log('{}')\n",
        )
        code, out, err = save_tool(
            self.root,
            "demo.node",
            "Print empty JSON from node",
            file_path=str(source),
        )
        self.assertIn(code, {1, 2})
        self.assertEqual(out, "")
        body = json.loads(err)
        self.assertEqual(body["error"], "unsupported_interpreter")
        self.assertIn("#!/usr/bin/env node", body["why"])
        self.assertNotIn("syntax error", body["why"].lower())
        self.assertNotIn("unexpected token", body["why"].lower())
        self.assertTrue(body["fix"].startswith("tk "))
        self.assertIn("--from-cmd", body["fix"])
        self.assertFalse((self.root / "tools" / "demo" / "node").exists())


class SaveFileInterpreterCliTests(unittest.TestCase):
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
        self._env = os.environ.copy()
        self._env["TK_NO_TELEMETRY"] = "1"
        self._env["TK_STATE_DIR"] = str(self.root / "state")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.tk), *args],
            capture_output=True,
            text=True,
            cwd=self.root,
            env=self._env,
        )

    def test_cli_save_headerless_python_then_run(self) -> None:
        source = Path(self._tmp.name) / "s.py"
        source.write_text("#!/usr/bin/env python3\nprint('{}')\n", encoding="utf-8")
        saved = self._run(
            "save",
            "demo.py",
            "--summary",
            "Print empty JSON",
            "--file",
            str(source),
        )
        self.assertEqual(saved.returncode, 0, saved.stderr)
        self.assertNotIn("syntax error", saved.stderr.lower())
        self.assertTrue(json.loads(saved.stdout)["ok"])
        ran = self._run("run", "demo.py")
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertEqual(json.loads(ran.stdout), {})


if __name__ == "__main__":
    unittest.main()
