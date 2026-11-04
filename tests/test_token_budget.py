"""Token-budget and wiki.lint gates from CODING_STANDARDS.md §3."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.catalog import find_items, format_find_output  # noqa: E402

LINT = ROOT / "tools" / "wiki" / "lint"
SKILL = ROOT / "skills" / "toolkit" / "SKILL.md"


def _run_lint(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(LINT), "--path", str(path)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )


class TokenBudgetTests(unittest.TestCase):
    def test_skill_stays_within_line_and_byte_ceiling(self):
        raw = SKILL.read_bytes()
        self.assertLessEqual(len(raw.splitlines()), 45)
        self.assertLessEqual(len(raw), 1800)

    def test_find_output_is_two_short_lines_per_item(self):
        items = find_items(ROOT)
        lines = format_find_output(items).splitlines()
        self.assertEqual(len(lines), 2 * len(items))
        for line in lines:
            self.assertLessEqual(len(line), 140)

    def test_repo_wiki_has_no_integrity_findings(self):
        proc = _run_lint(ROOT / "wiki")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["orphans"], [])
        self.assertEqual(payload["broken_links"], [])
        self.assertEqual(payload["undated_pages"], [])

    def test_broken_wiki_reports_orphan_broken_link_and_undated_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            wiki = Path(tmp)
            (wiki / "index.md").write_text(
                "# Index\n\n"
                "On 2026-11-04 see @abcdef1.\n\n"
                "- [good](good.md)\n"
                "- [missing](missing.md)\n"
                "- [plain](nodate.md)\n",
                encoding="utf-8",
            )
            (wiki / "good.md").write_text(
                "# Good\n\nOn 2026-11-04 commit @1234567.\n",
                encoding="utf-8",
            )
            (wiki / "orphan.md").write_text(
                "# Orphan\n\nOn 2026-11-04 commit @1234567.\n",
                encoding="utf-8",
            )
            (wiki / "nodate.md").write_text(
                "# Plain\n\nNo date and no commit citation.\n",
                encoding="utf-8",
            )
            proc = _run_lint(wiki)

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["orphans"], ["orphan.md"])
        self.assertEqual(
            payload["broken_links"],
            [{"source": "index.md", "target": "missing.md"}],
        )
        self.assertEqual(payload["undated_pages"], ["nodate.md"])


if __name__ == "__main__":
    unittest.main()
