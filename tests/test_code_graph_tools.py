"""Seams for code.imports, code.dependents, and code.blast-radius."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPORTS = ROOT / "tools/code/imports"
DEPENDENTS = ROOT / "tools/code/dependents"
CHAIN = ROOT / "chains/code.blast-radius.json"

APP_PY = """\
import os
import json
from pkg.util import helper
from .util import helper as helper2

text = "import ghost"
# import phantom
"""

UTIL_PY = """\
import sys

def helper():
    return 1
"""

JS_SRC = """\
import React from 'react';
import local from './util';
const extra = require('lodash');
// import skipped from 'not-real';
"""

GO_SRC = """\
package demo

import (
    "fmt"
    "pkg/util"
)
"""

SH_SRC = """\
#!/bin/sh
# source phantom
source ./util.sh
echo util
util --flag
"""


def _run(script: Path, env: dict, stdin: str = "") -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    for key in list(merged):
        if key.startswith("TK_ARG_") or key == "TK_DRY_RUN":
            merged.pop(key, None)
    merged.update(env)
    merged.setdefault("TK_DRY_RUN", "0")
    return subprocess.run(
        [sys.executable, str(script)],
        input=stdin,
        capture_output=True,
        text=True,
        env=merged,
    )


def _tree() -> tempfile.TemporaryDirectory:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    pkg = root / "pkg"
    pkg.mkdir()
    (pkg / "app.py").write_text(APP_PY, encoding="utf-8")
    (pkg / "util.py").write_text(UTIL_PY, encoding="utf-8")
    (root / "ui.js").write_text(JS_SRC, encoding="utf-8")
    (root / "main.go").write_text(GO_SRC, encoding="utf-8")
    script = root / "run.sh"
    script.write_text(SH_SRC, encoding="utf-8")
    script.chmod(0o755)
    skipped = root / "node_modules"
    skipped.mkdir()
    (skipped / "hidden.py").write_text("import secret_mod\n", encoding="utf-8")
    (root / ".hidden.py").write_text("import ghost_mod\n", encoding="utf-8")
    return tmp


class ImportsTests(unittest.TestCase):
    def test_classifies_internal_and_external(self) -> None:
        tmp = _tree()
        self.addCleanup(tmp.cleanup)
        proc = _run(IMPORTS, {"TK_ARG_PATH": tmp.name, "TK_ARG_LIMIT": "30"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["path"], tmp.name)
        self.assertGreaterEqual(payload["files_scanned"], 4)
        self.assertIn("os", payload["external"])
        self.assertIn("json", payload["external"])
        self.assertIn("sys", payload["external"])
        self.assertIn("react", payload["external"])
        self.assertIn("lodash", payload["external"])
        self.assertIn("fmt", payload["external"])
        self.assertIn("pkg", payload["internal"])
        self.assertTrue(any(name.startswith(".") for name in payload["internal"]))
        self.assertNotIn("ghost", payload["external"] + payload["internal"])
        self.assertNotIn("phantom", payload["external"] + payload["internal"])
        self.assertNotIn("secret_mod", payload["external"] + payload["internal"])
        self.assertNotIn("ghost_mod", payload["external"] + payload["internal"])
        by_file = {item["file"]: item["imports"] for item in payload["by_file"]}
        self.assertIn("os", by_file["pkg/app.py"])
        self.assertIn("pkg.util", by_file["pkg/app.py"])
        self.assertNotIn("ghost", by_file["pkg/app.py"])
        self.assertIn("react", by_file["ui.js"])
        self.assertIn("./util", by_file["ui.js"])
        self.assertIn("fmt", by_file["main.go"])
        self.assertEqual(payload["truncated"], 0)
        self.assertEqual(payload["internal"], sorted(payload["internal"]))
        self.assertEqual(payload["external"], sorted(payload["external"]))

    def test_by_file_limit(self) -> None:
        tmp = _tree()
        self.addCleanup(tmp.cleanup)
        proc = _run(IMPORTS, {"TK_ARG_PATH": tmp.name, "TK_ARG_LIMIT": "1"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(len(payload["by_file"]), 1)
        self.assertGreaterEqual(payload["truncated"], 1)
        self.assertGreater(len(payload["internal"]) + len(payload["external"]), 1)

    def test_dry_run(self) -> None:
        proc = _run(
            IMPORTS,
            {"TK_ARG_PATH": "lib", "TK_ARG_LIMIT": "20", "TK_DRY_RUN": "1"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            json.loads(proc.stdout),
            {"dry_run": True, "path": "lib", "limit": 20},
        )

    def test_extensionless_python_shebang_is_scanned(self) -> None:
        tmp = _tree()
        self.addCleanup(tmp.cleanup)
        script = Path(tmp.name) / "bin" / "tool"
        script.parent.mkdir()
        script.write_text(
            "#!/usr/bin/env python3\nimport pathlib\nfrom pkg.util import helper\n",
            encoding="utf-8",
        )
        proc = _run(IMPORTS, {"TK_ARG_PATH": tmp.name, "TK_ARG_LIMIT": "30"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        by_file = {item["file"]: item["imports"] for item in payload["by_file"]}
        self.assertIn("bin/tool", by_file)
        self.assertIn("pathlib", by_file["bin/tool"])
        self.assertIn("pkg.util", by_file["bin/tool"])
        self.assertIn("pathlib", payload["external"])


class DependentsTests(unittest.TestCase):
    def test_finds_import_statements_not_comments(self) -> None:
        tmp = _tree()
        self.addCleanup(tmp.cleanup)
        proc = _run(
            DEPENDENTS,
            {"TK_ARG_PATH": tmp.name, "TK_ARG_TARGET": "util", "TK_ARG_LIMIT": "30"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["target"], "util")
        self.assertEqual(payload["truncated"], 0)
        files = {item["file"] for item in payload["dependents"]}
        self.assertIn("pkg/app.py", files)
        self.assertIn("ui.js", files)
        self.assertIn("main.go", files)
        self.assertIn("run.sh", files)
        self.assertNotIn("pkg/util.py", files)
        app_lines = [item["statement"] for item in payload["dependents"] if item["file"] == "pkg/app.py"]
        self.assertTrue(any("pkg.util" in line for line in app_lines))
        self.assertTrue(any(".util" in line for line in app_lines))
        self.assertTrue(all("ghost" not in line and "phantom" not in line for line in app_lines))
        ordered = [(item["file"], item["line"]) for item in payload["dependents"]]
        self.assertEqual(ordered, sorted(ordered))
        self.assertEqual(payload["count"], len(payload["dependents"]))

    def test_limit(self) -> None:
        tmp = _tree()
        self.addCleanup(tmp.cleanup)
        proc = _run(
            DEPENDENTS,
            {"TK_ARG_PATH": tmp.name, "TK_ARG_TARGET": "util", "TK_ARG_LIMIT": "1"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(len(payload["dependents"]), 1)
        self.assertGreaterEqual(payload["truncated"], 1)

    def test_dry_run(self) -> None:
        proc = _run(
            DEPENDENTS,
            {
                "TK_ARG_PATH": ".",
                "TK_ARG_TARGET": "catalog",
                "TK_ARG_LIMIT": "20",
                "TK_DRY_RUN": "1",
            },
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            json.loads(proc.stdout),
            {"dry_run": True, "path": ".", "target": "catalog", "limit": 20},
        )

    def test_repo_catalog_dependents(self) -> None:
        proc = _run(
            DEPENDENTS,
            {
                "TK_ARG_PATH": str(ROOT),
                "TK_ARG_TARGET": "catalog",
                "TK_ARG_LIMIT": "80",
            },
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        files = {item["file"] for item in payload["dependents"]}
        self.assertIn("lib/runner.py", files)
        self.assertIn("lib/evolver.py", files)
        self.assertNotIn("lib/catalog.py", files)

    def test_extensionless_python_and_dotted_module(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "other_pkg").mkdir()
        (root / "other_pkg" / "util.py").write_text("x = 1\n", encoding="utf-8")
        (root / "caller.py").write_text(
            "import other_pkg.util\nimport pkg.util\nimport deep.pkg.util.more\n",
            encoding="utf-8",
        )
        tool = root / "hook"
        tool.write_text("#!/usr/bin/env python3\nfrom pkg.util import helper\n", encoding="utf-8")
        proc = _run(
            DEPENDENTS,
            {"TK_ARG_PATH": tmp.name, "TK_ARG_TARGET": "pkg.util", "TK_ARG_LIMIT": "30"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        files = {item["file"] for item in payload["dependents"]}
        self.assertIn("caller.py", files)
        self.assertIn("hook", files)
        statements = [item["statement"] for item in payload["dependents"] if item["file"] == "caller.py"]
        self.assertTrue(any("import pkg.util" in line for line in statements))
        self.assertTrue(any("deep.pkg.util" in line for line in statements))
        self.assertTrue(all("other_pkg.util" not in line for line in statements))
        hook_lines = [item["statement"] for item in payload["dependents"] if item["file"] == "hook"]
        self.assertTrue(any("pkg.util" in line for line in hook_lines))


class BlastRadiusTests(unittest.TestCase):
    def test_chain_contract_and_run(self) -> None:
        raw = json.loads(CHAIN.read_text(encoding="utf-8"))
        self.assertEqual(raw["name"], "code.blast-radius")
        self.assertEqual(raw["safety"], "read-only")
        self.assertEqual(raw["verified"], "2026-11-04")
        flags = {arg["flag"]: arg for arg in raw["args"]}
        self.assertTrue(flags["--path"]["required"])
        self.assertTrue(flags["--target"]["required"])
        self.assertEqual(raw["steps"][0]["tool"], "code.dependents")
        self.assertEqual(raw["steps"][0]["args"]["path"], "$input.path")
        self.assertEqual(raw["steps"][0]["args"]["target"], "$input.target")
        self.assertEqual(raw["steps"][1]["tool"], "json.pick")
        self.assertEqual(raw["steps"][1]["args"]["keys"], "target,count,truncated,dependents")

        env = os.environ.copy()
        env["TK_NO_TELEMETRY"] = "1"
        proc = subprocess.run(
            [str(ROOT / "tk"), "run", "code.blast-radius", "--path", str(ROOT), "--target", "catalog"],
            capture_output=True,
            text=True,
            env=env,
            cwd=ROOT,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(set(payload), {"target", "count", "truncated", "dependents"})
        files = {item["file"] for item in payload["dependents"]}
        self.assertIn("lib/runner.py", files)
        self.assertIn("lib/evolver.py", files)
        self.assertEqual(payload["target"], "catalog")


if __name__ == "__main__":
    unittest.main()
