"""@tk-keep skips unused prune. A missing header does not."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from lib.evolver import MIN_UNUSED_RUN_EVENTS, evolve_report


def _tool(path: Path, name: str, keep: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    extra = "# @tk-keep\n" if keep else ""
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


class KeepHeaderTests(unittest.TestCase):
    def test_keep_is_skipped_and_a_missing_header_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous = os.environ.get("TK_STATE_DIR")
            os.environ["TK_STATE_DIR"] = str(root / "state")
            try:
                _tool(root / "tools" / "lab" / "held", "lab.held", True)
                _tool(root / "tools" / "lab" / "stale", "lab.stale", False)
                past = datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp()
                for name in ("held", "stale"):
                    os.utime(root / "tools" / "lab" / name, (past, past))
                state = root / "state"
                state.mkdir()
                with (state / "events.jsonl").open("w", encoding="utf-8") as handle:
                    for _ in range(MIN_UNUSED_RUN_EVENTS):
                        handle.write(
                            json.dumps(
                                {"ts": "2020-06-01T00:00:00+00:00", "event": "run_ok", "name": "lab.other"},
                                separators=(",", ":"),
                            )
                            + "\n"
                        )
                report = evolve_report(root, auto_promote=False)
            finally:
                if previous is None:
                    os.environ.pop("TK_STATE_DIR", None)
                else:
                    os.environ["TK_STATE_DIR"] = previous
        self.assertNotIn("unused_reason", report)
        self.assertIn("lab.stale", report["unused_tools"])
        self.assertNotIn("lab.held", report["unused_tools"])
        self.assertEqual(report["telemetry"]["run_events"], MIN_UNUSED_RUN_EVENTS)


if __name__ == "__main__":
    unittest.main()
