"""A deprecated tool stays in the one catalog and names its replacement."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lib.catalog import find_items, format_find_output, format_info_output, parse_tool_header


def _tool(path: Path, name: str, deprecated: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    extra = f"# @tk-deprecated: {deprecated}\n" if deprecated else ""
    path.write_text(
        "#!/bin/bash\n"
        f"# @tk-name: {name}\n"
        "# @tk-summary: Echo a target id\n"
        "# @tk-safety: read-only\n"
        "# @tk-output: json | object\n"
        f"# @tk-example: tk run {name}\n"
        "# @tk-verified: none\n"
        f"{extra}"
        "printf '%s\\n' '{\"ok\":true}'\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


class DeprecatedToolTests(unittest.TestCase):
    def test_deprecated_tool_stays_findable_and_names_one_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _tool(root / "tools" / "old" / "echo", "old.echo", "new.echo")
            _tool(root / "tools" / "new" / "echo", "new.echo")
            found = find_items(root, "echo")
            names = [item["name"] for item in found]
            self.assertIn("old.echo", names)
            self.assertIn("new.echo", names)
            text = format_find_output(found)
            old = next(item for item in found if item["name"] == "old.echo")
            fresh = next(item for item in found if item["name"] == "new.echo")
        self.assertIn("instead: tk run new.echo", text)
        self.assertEqual(format_find_output([old]).count("\n"), 3)
        self.assertEqual(format_find_output([fresh]).count("\n"), 2)
        info = format_info_output(old)
        self.assertEqual(info.count("deprecated:"), 1)
        self.assertIn("deprecated: tk run new.echo", info)

    def test_header_tk_command_is_kept_as_one_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "echo"
            _tool(path, "old.echo", "tk run new.echo --target demo")
            item = parse_tool_header(path)
        self.assertEqual(_instead_of(item), "tk run new.echo --target demo")
        deprecated = [line for line in format_info_output(item).splitlines() if line.startswith("deprecated:")]
        self.assertEqual(deprecated, ["deprecated: tk run new.echo --target demo"])

    def test_catalog_is_still_one_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _tool(root / "tools" / "old" / "echo", "old.echo", "new.echo")
            from lib.catalog import discover_catalog

            catalog = discover_catalog(root)
        self.assertIsInstance(catalog, dict)
        self.assertIn("old.echo", catalog)
        self.assertNotIsInstance(catalog["old.echo"], list)


def _instead_of(item: dict) -> str:
    from lib.catalog import _instead

    return _instead(item)


if __name__ == "__main__":
    unittest.main()
