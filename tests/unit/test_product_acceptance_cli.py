from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "apps" / "api" / "scripts" / "run_local_product_acceptance.py"
SPEC = importlib.util.spec_from_file_location("run_local_product_acceptance", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
acceptance_cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acceptance_cli)


def test_concise_summary_reports_counts_and_unique_problem_codes(capsys) -> None:
    report = {
        "passed": False,
        "final_status": "FAILED",
        "release_candidate_eligible": False,
        "gate_summary": {
            "mandatory": 23,
            "mandatory_passed": 20,
            "mandatory_failed": 3,
            "mandatory_blocked": 0,
            "mandatory_capability_missing": 0,
        },
        "release_candidate_blockers": [
            {
                "phase_code": "organization",
                "gate_code": "organization_hierarchy",
                "error_code": "ACCEPTANCE_GATE_CONTRACT_INVALID",
            },
            {
                "phase_code": "enterprise_search",
                "gate_code": "enterprise_search_query",
                "error_code": "RESOURCE_LINEAGE_INCOMPLETE",
            },
        ],
        "blockers": [
            {
                "error_code": "RESOURCE_LINEAGE_INCOMPLETE",
                "details": {"large": "evidence"},
            },
            {
                "error_code": "EVIDENCE_PERSISTENCE_FAILED",
                "details": {"large": "evidence"},
            },
        ],
        "warnings": [],
    }

    summary = acceptance_cli.build_console_summary(report, "/tmp/acceptance.json")
    acceptance_cli.print_concise_summary(summary)

    output = capsys.readouterr().out
    assert "PRODUCT ACCEPTANCE: FAILED" in output
    assert "Mandatory gates: 20/23 passed" in output
    assert "Failures: 3 | Blocked: 0 | Missing capabilities: 0" in output
    assert "- organization/organization_hierarchy: ACCEPTANCE_GATE_CONTRACT_INVALID" in output
    assert "- enterprise_search/enterprise_search_query: RESOURCE_LINEAGE_INCOMPLETE" in output
    assert output.count("RESOURCE_LINEAGE_INCOMPLETE") == 1
    assert "- runtime: EVIDENCE_PERSISTENCE_FAILED" in output
    assert "large" not in output
    assert "Full report: /tmp/acceptance.json" in output
