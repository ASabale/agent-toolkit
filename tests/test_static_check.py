"""Default check and save do not start a tool. --verify uses the runner."""

from __future__ import annotations

import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lib.catalog import check_item  # noqa: E402
from lib.evolver import save_chain, save_tool, verify_item  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class StaticCheckTests(unittest.TestCase):
    def test_check_and_save_do_not_create_a_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "marker"
            draft = root / "draft.sh"
            draft.write_text(
                "#!/bin/bash\n"
                f"touch {marker}\n"
                "printf '%s\\n' 'not-json'\n",
                encoding="utf-8",
            )
            code, _out, err = save_tool(
                root,
                "lab.mark",
                "Create a marker",
                file_path=str(draft),
            )
            self.assertEqual(code, 0, err)
            self.assertFalse(marker.exists())
            result = check_item(root, "lab.mark")
            self.assertTrue(result["ok"], result)
            self.assertFalse(marker.exists())

    def test_verify_writer_and_chain_do_not_create_a_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "live-marker"
            body = (
                "#!/bin/bash\n"
                "# @tk-name: lab.touch\n"
                "# @tk-summary: Touch a marker outside dry-run\n"
                "# @tk-safety: mutating\n"
                "# @tk-output: json | object\n"
                "# @tk-example: tk run lab.touch\n"
                "# @tk-verified: none\n"
                "if [[ \"${TK_DRY_RUN:-0}\" == \"1\" ]]; then\n"
                "  printf '%s\\n' '{\"dry_run\":true,\"plan\":[\"touch\"]}'\n"
                "  exit 0\n"
                "fi\n"
                f"touch {marker}\n"
                "printf '%s\\n' '{\"ok\":true}'\n"
            )
            _write(root / "tools" / "lab" / "touch", body)
            checked = check_item(root, "lab.touch")
            self.assertTrue(checked["ok"], checked)
            self.assertFalse(marker.exists())
            status, payload = verify_item(root, "lab.touch")
            self.assertEqual(status, 0, payload)
            self.assertIs(payload.get("dry_run"), True)
            self.assertFalse(marker.exists())

            chain_code, _cout, cerr = save_chain(
                root,
                "lab.pipeline",
                "Run the mutating step",
                [{"tool": "lab.touch", "args": {}}],
            )
            self.assertEqual(chain_code, 0, cerr)
            chain_check = check_item(root, "lab.pipeline")
            self.assertTrue(chain_check["ok"], chain_check)
            self.assertFalse(marker.exists())
            chain_status, chain_payload = verify_item(root, "lab.pipeline")
            self.assertEqual(chain_status, 0, chain_payload)
            self.assertIs(chain_payload.get("dry_run"), True)
            self.assertFalse(marker.exists())

    def test_syntax_check_leaves_no_new_file_in_the_toolkit_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "tools" / "lab" / "py"
            _write(
                path,
                "#!/usr/bin/env python3\n"
                "# @tk-name: lab.py\n"
                "# @tk-summary: Syntax only\n"
                "# @tk-safety: read-only\n"
                "# @tk-output: json | object\n"
                "# @tk-example: tk run lab.py\n"
                "# @tk-verified: none\n"
                "print('{\"ok\": true}')\n",
            )
            before = {item.relative_to(root) for item in root.rglob("*")}
            result = check_item(root, "lab.py")
            after = {item.relative_to(root) for item in root.rglob("*")}
        self.assertTrue(result["ok"], result)
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
