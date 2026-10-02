#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.quality_gate_results import REQUIRED_STAGE_BLOCKING, aggregate_results


def passing_stages() -> dict[str, dict[str, object]]:
    return {
        name: {"status": "passed", "blocking": blocking, "exit_code": 0}
        for name, blocking in REQUIRED_STAGE_BLOCKING.items()
    }


class QualityGateResultAggregatorTests(unittest.TestCase):
    def test_all_blocking_stages_pass(self) -> None:
        result = aggregate_results(passing_stages())
        self.assertEqual(result["overall_status"], "passed")
        self.assertEqual(result["overall_exit_code"], 0)

    def test_informational_failure_does_not_fail_gate(self) -> None:
        stages = passing_stages()
        stages["python_audit"].update(status="failed", exit_code=1)
        result = aggregate_results(stages)
        self.assertEqual(result["overall_status"], "passed")
        self.assertEqual(result["overall_exit_code"], 0)

    def test_editorial_audit_failure_does_not_fail_gate(self) -> None:
        stages = passing_stages()
        stages["portal_editorial_audit"].update(status="failed", exit_code=1)
        result = aggregate_results(stages)
        self.assertEqual(result["overall_status"], "passed")
        self.assertEqual(result["overall_exit_code"], 0)

    def test_blocking_failure_fails_gate(self) -> None:
        stages = passing_stages()
        stages["backend_tests"].update(status="failed", exit_code=1)
        result = aggregate_results(stages)
        self.assertEqual(result["overall_status"], "failed")
        self.assertEqual(result["overall_exit_code"], 1)

    def test_cleanup_failure_fails_gate(self) -> None:
        stages = passing_stages()
        stages["cleanup_status"].update(status="failed", exit_code=1)
        result = aggregate_results(stages)
        self.assertEqual(result["overall_status"], "failed")
        self.assertIn("cleanup_status", result["blocking_failures"])

    def test_missing_blocking_stage_fails_gate(self) -> None:
        stages = passing_stages()
        del stages["migrations"]
        result = aggregate_results(stages)
        self.assertEqual(result["overall_status"], "failed")
        self.assertEqual(result["overall_exit_code"], 1)
        self.assertIn("migrations", result["missing_stages"])


if __name__ == "__main__":
    unittest.main()
