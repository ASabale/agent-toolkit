"""Seams for code.symbols and code.search."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYMBOLS = ROOT / "tools/code/symbols"
SEARCH = ROOT / "tools/code/search"

PY_SRC = """\
class Alpha:
    def greet(self, name):
        return name

async def load(url, timeout=1):
    pass

def helper(a, b=1, *rest, flag, **kw):
    def inner():
        return a
    return inner
"""

JS_SRC = """\
export class Panel {
  render() { return 1; }
}
export async function greet(name) {
  return name;
}
function local(a, b) {}
"""

TS_SRC = """\
export class Box {
  value: number;
}
export function id(value: string) {
  return value;
}
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


class SymbolsTests(unittest.TestCase):
    def _tree(self) -> tempfile.TemporaryDirectory:
        tmp = tempfile.TemporaryDirectory()
        root = Path(tmp.name)
        (root / "pkg").mkdir()
        (root / "pkg" / "widget.py").write_text(PY_SRC, encoding="utf-8")
        (root / "ui.js").write_text(JS_SRC, encoding="utf-8")
        (root / "ui.ts").write_text(TS_SRC, encoding="utf-8")
        skipped = root / "node_modules"
        skipped.mkdir()
        (skipped / "hidden.py").write_text("def secret():\n    pass\n", encoding="utf-8")
        (root / ".hidden.py").write_text("def ghost():\n    pass\n", encoding="utf-8")
        return tmp

    def test_extracts_python_and_js_symbols(self) -> None:
        tmp = self._tree()
        self.addCleanup(tmp.cleanup)
        proc = _run(
            SYMBOLS,
            {"TK_ARG_PATH": tmp.name, "TK_ARG_KIND": "all", "TK_ARG_LIMIT": "40"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["path"], tmp.name)
        self.assertEqual(payload["kind"], "all")
        self.assertEqual(payload["truncated"], 0)
        found = {(item["file"], item["kind"], item["name"], item["signature"]) for item in payload["symbols"]}
        self.assertIn(("pkg/widget.py", "class", "Alpha", "()"), found)
        self.assertIn(("pkg/widget.py", "function", "greet", "(self, name)"), found)
        self.assertIn(("pkg/widget.py", "async_function", "load", "(url, timeout)"), found)
        self.assertIn(("pkg/widget.py", "function", "helper", "(a, b, *rest, flag, **kw)"), found)
        self.assertNotIn("inner", {item["name"] for item in payload["symbols"]})
        self.assertIn(("ui.js", "class", "Panel", "()"), found)
        self.assertIn(("ui.js", "async_function", "greet", "(name)"), found)
        self.assertIn(("ui.js", "function", "local", "(a, b)"), found)
        self.assertIn(("ui.ts", "class", "Box", "()"), found)
        self.assertIn(("ui.ts", "function", "id", "(value: string)"), found)
        self.assertNotIn("secret", {item["name"] for item in payload["symbols"]})
        self.assertNotIn("ghost", {item["name"] for item in payload["symbols"]})
        self.assertEqual(payload["count"], len(payload["symbols"]))

    def test_kind_class_and_limit_truncation(self) -> None:
        tmp = self._tree()
        self.addCleanup(tmp.cleanup)
        proc = _run(
            SYMBOLS,
            {"TK_ARG_PATH": tmp.name, "TK_ARG_KIND": "class", "TK_ARG_LIMIT": "40"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["kind"], "class")
        self.assertEqual({item["name"] for item in payload["symbols"]}, {"Alpha", "Panel", "Box"})
        self.assertTrue(all(item["kind"] == "class" for item in payload["symbols"]))

        functions = _run(
            SYMBOLS,
            {"TK_ARG_PATH": tmp.name, "TK_ARG_KIND": "function", "TK_ARG_LIMIT": "40"},
        )
        self.assertEqual(functions.returncode, 0, functions.stderr)
        function_rows = json.loads(functions.stdout)
        self.assertEqual(function_rows["kind"], "function")
        found = {(item["file"], item["kind"], item["name"]) for item in function_rows["symbols"]}
        self.assertIn(("pkg/widget.py", "function", "greet"), found)
        self.assertIn(("pkg/widget.py", "async_function", "load"), found)
        self.assertIn(("ui.js", "async_function", "greet"), found)
        self.assertNotIn("Alpha", {item["name"] for item in function_rows["symbols"]})

        async_only = _run(
            SYMBOLS,
            {"TK_ARG_PATH": tmp.name, "TK_ARG_KIND": "async_function", "TK_ARG_LIMIT": "40"},
        )
        self.assertEqual(async_only.returncode, 0, async_only.stderr)
        async_rows = json.loads(async_only.stdout)
        self.assertGreaterEqual(async_rows["count"], 1)
        self.assertTrue(all(item["kind"] == "async_function" for item in async_rows["symbols"]))
        self.assertIn("load", {item["name"] for item in async_rows["symbols"]})

        limited = _run(
            SYMBOLS,
            {"TK_ARG_PATH": tmp.name, "TK_ARG_KIND": "all", "TK_ARG_LIMIT": "2"},
        )
        self.assertEqual(limited.returncode, 0, limited.stderr)
        capped = json.loads(limited.stdout)
        self.assertEqual(len(capped["symbols"]), 2)
        self.assertEqual(capped["count"], 2)
        self.assertGreaterEqual(capped["truncated"], 1)

    def test_dry_run(self) -> None:
        proc = _run(
            SYMBOLS,
            {
                "TK_ARG_PATH": "example",
                "TK_ARG_KIND": "all",
                "TK_ARG_LIMIT": "40",
                "TK_DRY_RUN": "1",
            },
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(
            payload,
            {"dry_run": True, "path": "example", "kind": "all", "limit": 40},
        )


class SearchTests(unittest.TestCase):
    def test_glob_and_line_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.py").write_text("keep needle here\nother\n", encoding="utf-8")
            (root / "b.js").write_text("needle in js\n", encoding="utf-8")
            (root / "long.py").write_text("needle " + ("x" * 200) + "\n", encoding="utf-8")
            (root / "bin.py").write_bytes(b"needle\x00hidden\n")
            nested = root / ".git"
            nested.mkdir()
            (nested / "skip.py").write_text("needle\n", encoding="utf-8")
            proc = _run(
                SEARCH,
                {
                    "TK_ARG_PATH": tmp,
                    "TK_ARG_PATTERN": "needle",
                    "TK_ARG_GLOB": "*.py",
                    "TK_ARG_LIMIT": "30",
                },
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        files = {item["file"] for item in payload["matches"]}
        self.assertEqual(files, {"a.py", "long.py"})
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["truncated"], 0)
        long = next(item for item in payload["matches"] if item["file"] == "long.py")
        self.assertEqual(len(long["text"]), 160)
        self.assertTrue(long["text"].startswith("needle "))
        self.assertEqual(payload["pattern"], "needle")

    def test_invalid_regex(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = _run(
                SEARCH,
                {
                    "TK_ARG_PATH": tmp,
                    "TK_ARG_PATTERN": "(",
                    "TK_ARG_GLOB": "all",
                    "TK_ARG_LIMIT": "30",
                },
            )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "")
        err = json.loads(proc.stderr)
        self.assertEqual(err["error"], "invalid_regex")
        self.assertIn("why", err)
        self.assertIn("fix", err)

    def test_limit_reports_omitted_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "notes.txt").write_text("hit\nhit\nhit\n", encoding="utf-8")
            proc = _run(
                SEARCH,
                {
                    "TK_ARG_PATH": tmp,
                    "TK_ARG_PATTERN": "hit",
                    "TK_ARG_GLOB": "all",
                    "TK_ARG_LIMIT": "1",
                },
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["truncated"], 2)
        self.assertEqual(payload["matches"][0]["line"], 1)

    def test_dry_run(self) -> None:
        proc = _run(
            SEARCH,
            {
                "TK_ARG_PATH": "example",
                "TK_ARG_PATTERN": "example",
                "TK_ARG_GLOB": "all",
                "TK_ARG_LIMIT": "30",
                "TK_DRY_RUN": "1",
            },
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["path"], "example")
        self.assertEqual(payload["pattern"], "example")
        self.assertEqual(payload["limit"], 30)


class ModuleSurfaceTests(unittest.TestCase):
    def test_symbols_run_keeps_kind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "mod.py").write_text("class Surface:\n    pass\n", encoding="utf-8")
            env = os.environ.copy()
            env["TK_NO_TELEMETRY"] = "1"
            proc = subprocess.run(
                [str(ROOT / "tk"), "run", "code.symbols", "--path", tmp],
                capture_output=True,
                text=True,
                env=env,
                cwd=ROOT,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(set(payload), {"path", "kind", "count", "truncated", "symbols"})
        self.assertEqual(payload["kind"], "all")
        self.assertEqual(payload["symbols"][0]["name"], "Surface")


if __name__ == "__main__":
    unittest.main()
