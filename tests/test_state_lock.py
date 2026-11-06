"""Advisory locks for telemetry and the audit log."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from lib.evolver import append_audit, write_state_json
from lib.runner import run_tool

ROOT = Path(__file__).resolve().parents[1]


class StateLockTests(unittest.TestCase):
    def test_two_processes_do_not_tear_a_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            env = os.environ.copy()
            env.pop("TK_NO_TELEMETRY", None)
            env["TK_STATE_DIR"] = str(state)
            env["ROOT"] = str(ROOT)
            script = (
                "import os\n"
                "from pathlib import Path\n"
                "from lib.evolver import log_event\n"
                "root = Path(os.environ['TK_STATE_DIR']).parent\n"
                "for i in range(30):\n"
                "    log_event(root, 'search_miss', {'query': 'q' * 120, 'i': i, 'pid': os.getpid()})\n"
            )
            procs = [
                subprocess.Popen(
                    ["python3", "-c", script],
                    cwd=str(ROOT),
                    env=env,
                )
                for _ in range(2)
            ]
            codes = [proc.wait(timeout=30) for proc in procs]
            self.assertEqual(codes, [0, 0])
            lines = (state / "events.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 60)
            for line in lines:
                self.assertTrue(line.endswith("}"))
                json.loads(line)

    def test_write_error_keeps_find_alive(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocked = Path(tmp) / "state"
            blocked.write_text("not-a-directory", encoding="utf-8")
            env = os.environ.copy()
            env.pop("TK_NO_TELEMETRY", None)
            env["TK_STATE_DIR"] = str(blocked)
            proc = subprocess.run(
                [str(ROOT / "tk"), "find", "env"],
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_audit_failure_denies_a_mutating_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "mutated"
            tool = root / "touch"
            tool.write_text(
                "#!/bin/bash\n"
                "if [[ \"${TK_DRY_RUN:-0}\" == \"1\" ]]; then\n"
                "  printf '%s\\n' '{\"dry_run\":true,\"plan\":[\"touch\"]}'\n"
                "  exit 0\n"
                "fi\n"
                "printf '%s\\n' '{\"ok\":true}'\n"
                f"touch {marker}\n",
                encoding="utf-8",
            )
            tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
            blocked = root / "state"
            blocked.write_text("not-a-directory", encoding="utf-8")
            env_state = os.environ.get("TK_STATE_DIR")
            os.environ["TK_STATE_DIR"] = str(blocked)
            try:
                code, _out, err = run_tool(
                    root,
                    {
                        "name": "demo.touch",
                        "path": str(tool),
                        "safety": "mutating",
                        "args": [],
                        "example": "tk run demo.touch --yes",
                        "kind": "tool",
                    },
                    {},
                    confirmed=True,
                )
            finally:
                if env_state is None:
                    os.environ.pop("TK_STATE_DIR", None)
                else:
                    os.environ["TK_STATE_DIR"] = env_state
            self.assertEqual(code, 1)
            self.assertIn("audit_failed", err)
            self.assertFalse(marker.exists())

    def test_state_json_replaces_under_the_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous = os.environ.pop("TK_STATE_DIR", None)
            try:
                write_state_json(root, "policy.json", {"ok": True})
                payload = json.loads((root / "state" / "policy.json").read_text(encoding="utf-8"))
            finally:
                if previous is not None:
                    os.environ["TK_STATE_DIR"] = previous
            self.assertEqual(payload["ok"], True)
            self.assertFalse((root / "state" / "policy.json.tmp").exists())

    def test_audit_line_records_flock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous = os.environ.pop("TK_STATE_DIR", None)
            try:
                self.assertTrue(append_audit(root, {"name": "demo.touch", "decision": "allow", "exit": 0}))
                line = json.loads((root / "state" / "audit.jsonl").read_text(encoding="utf-8"))
            finally:
                if previous is not None:
                    os.environ["TK_STATE_DIR"] = previous
            self.assertEqual(line["lock"], "flock")
            self.assertNotIn("O_APPEND", json.dumps(line))


if __name__ == "__main__":
    unittest.main()
