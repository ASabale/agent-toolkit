"""Seams for md.section and pkg.manifest-digest."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECTION = ROOT / "tools/md/section"
DIGEST = ROOT / "tools/pkg/manifest-digest"
VISION = ROOT / "VISION.md"

FENCED = """\
# Real Title

```python
# not a heading
x = 1
```

~~~
# also not a heading
~~~

## Core Problem

Agents need less context.

### Nested

detail

## Next

after
"""


def _run(script: Path, env: dict) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    for key in list(merged):
        if key.startswith("TK_ARG_") or key == "TK_DRY_RUN":
            merged.pop(key, None)
    merged.update(env)
    merged.setdefault("TK_DRY_RUN", "0")
    return subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        env=merged,
    )


class SectionTests(unittest.TestCase):
    def test_outline_ignores_fenced_hash_comments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.md"
            path.write_text(FENCED, encoding="utf-8")
            result = _run(
                SECTION,
                {"TK_ARG_PATH": str(path), "TK_ARG_HEADING": "outline", "TK_ARG_MAX_LINES": "60"},
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        titles = [item["title"] for item in payload["headings"]]
        self.assertEqual(titles, ["Real Title", "Core Problem", "Nested", "Next"])
        self.assertEqual(payload["mode"], "outline")
        self.assertEqual(payload["count"], 4)

    def test_vision_outline_and_section(self) -> None:
        outline = _run(
            SECTION,
            {"TK_ARG_PATH": str(VISION), "TK_ARG_HEADING": "outline", "TK_ARG_MAX_LINES": "40"},
        )
        self.assertEqual(outline.returncode, 0, outline.stderr)
        headings = json.loads(outline.stdout)["headings"]
        self.assertTrue(any("Core Problem" in item["title"] for item in headings))
        self.assertTrue(all(item["title"] != "not a heading" for item in headings))

        section = _run(
            SECTION,
            {"TK_ARG_PATH": str(VISION), "TK_ARG_HEADING": "core problem", "TK_ARG_MAX_LINES": "60"},
        )
        self.assertEqual(section.returncode, 0, section.stderr)
        body = json.loads(section.stdout)
        self.assertIn("Core Problem", body["heading"])
        self.assertEqual(body["level"], 2)
        self.assertIn("System Context Bloat", body["content"])
        self.assertNotIn("Purpose & Core Principles", body["content"])
        self.assertEqual(body["truncated"], 0)

    def test_missing_heading(self) -> None:
        result = _run(
            SECTION,
            {"TK_ARG_PATH": str(VISION), "TK_ARG_HEADING": "no-such-heading-xyz"},
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        err = json.loads(result.stderr)
        self.assertEqual(err["error"], "heading_not_found")

    def test_outline_truncation_and_literal_outline_heading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.md"
            path.write_text(
                "# Outline\n\nsection body\n\n## Later\n\nmore\n",
                encoding="utf-8",
            )
            outline = _run(
                SECTION,
                {"TK_ARG_PATH": str(path), "TK_ARG_OUTLINE": "true", "TK_ARG_MAX_LINES": "1"},
            )
            literal = _run(
                SECTION,
                {"TK_ARG_PATH": str(path), "TK_ARG_HEADING": "Outline", "TK_ARG_MAX_LINES": "60"},
            )
        self.assertEqual(outline.returncode, 0, outline.stderr)
        tree = json.loads(outline.stdout)
        self.assertEqual(tree["mode"], "outline")
        self.assertEqual(tree["count"], 1)
        self.assertEqual(tree["truncated"], 1)
        self.assertEqual([item["title"] for item in tree["headings"]], ["Outline"])
        self.assertEqual(literal.returncode, 0, literal.stderr)
        body = json.loads(literal.stdout)
        self.assertEqual(body["heading"], "Outline")
        self.assertEqual(body["level"], 1)
        self.assertIn("section body", body["content"])
        self.assertNotIn("mode", body)


class ManifestTests(unittest.TestCase):
    def test_digest_package_pyproject_and_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(
                json.dumps(
                    {
                        "name": "widget",
                        "version": "1.2.3",
                        "scripts": {"test": "pytest"},
                        "dependencies": {"left-pad": "1.0.0"},
                        "devDependencies": {"typescript": "5.0.0"},
                    }
                ),
                encoding="utf-8",
            )
            (root / "pyproject.toml").write_text(
                '[project]\nname = "widget-py"\nversion = "0.1.0"\ndependencies = [\n  "requests>=2",\n]\n',
                encoding="utf-8",
            )
            (root / "requirements.txt").write_text("flask==3.0.0\n# comment\n", encoding="utf-8")
            result = _run(DIGEST, {"TK_ARG_PATH": str(root), "TK_ARG_LIMIT": "30"})
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["manifests"], ["package.json", "pyproject.toml", "requirements.txt"])
        self.assertEqual(payload["name"], "widget")
        self.assertEqual(payload["version"], "1.2.3")
        self.assertEqual(payload["scripts"], {"test": "pytest"})
        self.assertEqual(payload["dependencies"], ["left-pad", "requests", "flask"])
        self.assertEqual(payload["dev_dependencies"], ["typescript"])
        self.assertEqual(payload["truncated"], 0)

    def test_limit_sets_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "requirements.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
            result = _run(DIGEST, {"TK_ARG_PATH": str(root), "TK_ARG_LIMIT": "1"})
        payload = json.loads(result.stdout)
        self.assertEqual(payload["dependencies"], ["alpha"])
        self.assertEqual(payload["truncated"], 2)

    def test_pep508_extras_markers_and_missing_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "requirements.txt").write_text(
                'requests[security]>=2.0\ntomli;python_version<"3.11"\n',
                encoding="utf-8",
            )
            parsed = _run(DIGEST, {"TK_ARG_PATH": str(root), "TK_ARG_LIMIT": "30"})
            empty = Path(tmp) / "empty"
            empty.mkdir()
            missing = _run(DIGEST, {"TK_ARG_PATH": str(empty), "TK_ARG_LIMIT": "30"})
            notes = Path(tmp) / "notes.txt"
            notes.write_text("hello\n", encoding="utf-8")
            unsupported = _run(DIGEST, {"TK_ARG_PATH": str(notes), "TK_ARG_LIMIT": "30"})
        self.assertEqual(parsed.returncode, 0, parsed.stderr)
        self.assertEqual(json.loads(parsed.stdout)["dependencies"], ["requests", "tomli"])
        for result, raw in ((missing, str(empty)), (unsupported, str(notes))):
            self.assertEqual(result.returncode, 1)
            err = json.loads(result.stderr)
            self.assertEqual(err["error"], "no_manifest_found")
            self.assertIn(raw, err["why"])


if __name__ == "__main__":
    unittest.main()
