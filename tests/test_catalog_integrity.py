"""Catalog name uniqueness and tools/<namespace>/<file> layout checks."""

import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.catalog import check_all, check_item, discover_catalog  # noqa: E402


def _write(path: Path, text: str, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    mode = stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH
    if executable:
        mode |= stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    path.chmod(mode)


def _bash_tool(name: str, summary: str = "Integrity fixture") -> str:
    return (
        "#!/usr/bin/env bash\n"
        f"# @tk-name: {name}\n"
        f"# @tk-summary: {summary}\n"
        "# @tk-safety: read-only\n"
        "# @tk-output: json | object\n"
        f"# @tk-example: tk run {name}\n"
        "# @tk-verified: none\n"
        "\n"
        "if [[ \"${TK_DRY_RUN:-0}\" == \"1\" ]]; then\n"
        "  printf '%s\\n' '{\"dry_run\":true}'\n"
        "  exit 0\n"
        "fi\n"
        "printf '%s\\n' '{\"ok\":true}'\n"
    )


def _chain(name: str, steps=None) -> str:
    return json.dumps({
        "name": name,
        "summary": "Integrity fixture chain",
        "safety": "read-only",
        "args": [],
        "steps": steps if steps is not None else [],
        "output": "json | object",
        "example": f"tk run {name}",
        "verified": "none",
    })


class CatalogIntegrityTests(unittest.TestCase):
    def test_duplicate_tool_name_under_second_path_fails_and_names_both(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "tools" / "env" / "check", _bash_tool("env.check"), executable=True)
            _write(root / "tools" / "zz" / "other", _bash_tool("env.check"), executable=True)
            result = check_item(root, "env.check")
            report = check_all(root)
            catalog = discover_catalog(root)
        self.assertEqual(list(catalog), ["env.check"])
        self.assertEqual(catalog["env.check"]["kind"], "tool")
        self.assertFalse(result["ok"])
        self.assertIn(
            "duplicate name: env.check (tools/env/check, tools/zz/other)",
            result["errors"],
        )
        self.assertFalse(report["ok"])
        self.assertTrue(
            any("tools/env/check" in err and "tools/zz/other" in err for err in report["errors"])
        )

    def test_chain_name_colliding_with_tool_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(
                root / "tools" / "git" / "branch-digest",
                _bash_tool("git.branch-digest"),
                executable=True,
            )
            chain = root / "chains" / "zz.json"
            chain.parent.mkdir(parents=True)
            chain.write_text(_chain("git.branch-digest"), encoding="utf-8")
            result = check_item(root, "git.branch-digest")
            report = check_all(root)
            catalog = discover_catalog(root)
        self.assertEqual(catalog["git.branch-digest"]["kind"], "tool")
        self.assertFalse(result["ok"])
        self.assertIn(
            "duplicate name: git.branch-digest (tools/git/branch-digest, chains/zz.json)",
            result["errors"],
        )
        self.assertFalse(report["ok"])

    def test_tool_name_path_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "tools" / "a" / "b"
            _write(path, _bash_tool("a.c"), executable=True)
            result = check_item(root, path)
        self.assertFalse(result["ok"])
        self.assertIn(
            "name/path mismatch: @tk-name a.c but path implies a.b",
            result["errors"],
        )

    def test_chain_name_must_equal_json_stem(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chain = root / "chains" / "demo.pipeline.json"
            chain.parent.mkdir(parents=True)
            chain.write_text(_chain("other.name"), encoding="utf-8")
            result = check_item(root, chain)
        self.assertFalse(result["ok"])
        self.assertIn(
            "name/path mismatch: @tk-name other.name but path implies demo.pipeline",
            result["errors"],
        )

    def test_discover_catalog_is_first_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "tools" / "demo" / "echo", _bash_tool("demo.echo"), executable=True)
            chain = root / "chains" / "later.json"
            chain.parent.mkdir(parents=True)
            chain.write_text(_chain("demo.echo"), encoding="utf-8")
            catalog = discover_catalog(root)
        self.assertEqual(catalog["demo.echo"]["kind"], "tool")
        self.assertTrue(catalog["demo.echo"]["path"].endswith("tools/demo/echo"))

    def test_unique_matching_names_still_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / "tools" / "demo" / "echo", _bash_tool("demo.echo"), executable=True)
            chain = root / "chains" / "demo.pipeline.json"
            chain.parent.mkdir(parents=True)
            chain.write_text(_chain("demo.pipeline", steps=[{"tool": "demo.echo"}]), encoding="utf-8")
            tool = check_item(root, "demo.echo")
            pipeline = check_item(root, "demo.pipeline")
            report = check_all(root)
        self.assertTrue(tool["ok"], tool["errors"])
        self.assertTrue(pipeline["ok"], pipeline["errors"])
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["checked"], 2)


if __name__ == "__main__":
    unittest.main()
