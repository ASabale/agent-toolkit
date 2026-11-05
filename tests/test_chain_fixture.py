"""Temporary executables composed through the real catalog scanner.

Nothing here is committed under tools/ or chains/.
"""

from __future__ import annotations

import json
import os
import stat
import unittest
from pathlib import Path

from lib.catalog import discover_catalog
from lib.runner import run_chain

ROOT = Path(__file__).resolve().parents[1]


def _tool(path: Path, name: str, arg: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/bin/sh\n"
        f"# @tk-name: {name}\n"
        "# @tk-summary: Fixture step for the chain demonstration\n"
        "# @tk-safety: read-only\n"
        f"# @tk-arg: --{arg} | required | string | Fixture input\n"
        "# @tk-output: json | fixture payload\n"
        f"# @tk-example: tk run {name} --{arg} value\n"
        f"{body}",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


class ChainFixtureTests(unittest.TestCase):
    def test_passes_a_field_and_stops_before_the_last_step(self) -> None:
        production = set(discover_catalog(ROOT))
        env = os.environ.copy()
        os.environ["TK_NO_TELEMETRY"] = "1"
        try:
            self._run(production)
        finally:
            os.environ.clear()
            os.environ.update(env)

    def _run(self, production: set[str]) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "step3-ran"
            _tool(
                root / "tools" / "fixture" / "revision",
                "fixture.revision",
                "revision",
                'printf \'{"revision":"%s"}\\n\' "$TK_ARG_REVISION"\n',
            )
            _tool(
                root / "tools" / "fixture" / "build",
                "fixture.build",
                "revision",
                "if [ \"$TK_ARG_REVISION\" = \"bad\" ]; then\n"
                "  printf '%s\\n' "
                "'{\"error\":\"build_failed\",\"why\":\"revision rejected\","
                "\"fix\":\"tk run fixture.build --revision abc\"}' >&2\n"
                "  exit 4\n"
                "fi\n"
                'printf \'{"revision":"%s","status":"green"}\\n\' "$TK_ARG_REVISION"\n',
            )
            _tool(
                root / "tools" / "fixture" / "report",
                "fixture.report",
                "revision",
                f"printf 'ran\\n' > '{marker}'\n"
                'printf \'{"revision":"%s","reported":true}\\n\' "$TK_ARG_REVISION"\n',
            )
            chain_path = root / "chains" / "fixture.ship.json"
            chain_path.parent.mkdir()
            chain_path.write_text(
                json.dumps(
                    {
                        "kind": "chain",
                        "name": "fixture.ship",
                        "summary": "Pass a revision through two checks",
                        "safety": "read-only",
                        "args": [
                            {
                                "flag": "--revision",
                                "required": True,
                                "type": "string",
                                "description": "Revision to carry",
                            }
                        ],
                        "steps": [
                            {
                                "tool": "fixture.revision",
                                "args": {"revision": "$input.revision"},
                            },
                            {
                                "tool": "fixture.build",
                                "args": {"revision": "$prev.revision"},
                            },
                            {
                                "tool": "fixture.report",
                                "args": {"revision": "$prev.revision"},
                            },
                        ],
                        "output": "json | {revision, reported}",
                        "example": "tk run fixture.ship --revision abc",
                    }
                ),
                encoding="utf-8",
            )
            catalog = discover_catalog(root)
            self.assertEqual(
                set(catalog),
                {"fixture.revision", "fixture.build", "fixture.report", "fixture.ship"},
            )
            code, out, err = run_chain(
                root, catalog["fixture.ship"], {"--revision": "abc"}
            )
            self.assertEqual(code, 0, err)
            self.assertEqual(json.loads(out)["revision"], "abc")
            self.assertTrue(json.loads(out)["reported"])
            self.assertEqual(marker.read_text(encoding="utf-8"), "ran\n")

            marker.unlink()
            code, out, err = run_chain(
                root, catalog["fixture.ship"], {"--revision": "bad"}
            )
            self.assertEqual(code, 4)
            self.assertEqual(out, "")
            payload = json.loads(err)
            self.assertIn(
                "chain fixture.ship stopped at step 2/3 (fixture.build):",
                payload["why"],
            )
            self.assertFalse(marker.exists())

        self.assertEqual(set(discover_catalog(ROOT)), production)
