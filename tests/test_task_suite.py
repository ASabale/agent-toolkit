"""Scripted task scores stay out of the model object."""

import json
import subprocess
import unittest
from pathlib import Path

from bench.task_suite import TASK_IDS, run_suite

ROOT = Path(__file__).resolve().parents[1]
_METRICS = (
    "first_attempt_success",
    "turns",
    "tool_calls",
    "context_tokens",
    "recovery_success",
    "execution_failure",
    "elapsed_ms",
    "authorization_violation",
)


class TaskSuiteTests(unittest.TestCase):
    def test_scripted_suite_keeps_model_empty(self) -> None:
        report = run_suite(ROOT)
        scripted = report["scripted"]["tasks"]
        model = report["model"]
        self.assertEqual([row["id"] for row in scripted], list(TASK_IDS))
        self.assertEqual([row["id"] for row in model["tasks"]], list(TASK_IDS))
        migrate = scripted[-1]
        self.assertEqual(migrate["id"], "migrate_dry_run")
        self.assertFalse(migrate["scored"])
        self.assertIsNone(migrate["first_attempt_success"])
        scored = [row for row in scripted if row["id"] != "migrate_dry_run"]
        self.assertEqual(len(scored), 8)
        for row in scored:
            self.assertTrue(row["scored"], row["id"])
            self.assertTrue(row["first_attempt_success"], row)
            self.assertFalse(row["authorization_violation"], row["id"])
        self.assertIsNone(model["model_id"])
        self.assertIsNone(model["harness_id"])
        self.assertIsNone(model["toolkit_commit"])
        for row in model["tasks"]:
            for key in _METRICS:
                self.assertIsNone(row[key], row["id"])
        for source, copy in zip(scripted, model["tasks"]):
            if source["first_attempt_success"] is None:
                continue
            self.assertIsNone(copy["first_attempt_success"])

    def test_token_benchmark_still_runs(self) -> None:
        proc = subprocess.run(
            ["python3", "bench/mcp_vs_tk.py", "--json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload)


if __name__ == "__main__":
    unittest.main()
