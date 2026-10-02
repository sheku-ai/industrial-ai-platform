#!/usr/bin/env python3
"""Fast contract for projecting diagnostics evidence into platform journey."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.platform_journey_evidence import (  # noqa: E402
    build_platform_journey_from_diagnostics_evidence,
)


def sample_diagnostics_evidence() -> dict:
    diagnostics = {
        "platform": {"name": "Industrial AI Platform", "version": "v1.3.1", "release_stage": "PRE-PRODUCTION"},
        "runtime_profiles": {
            "core": {"ready": True, "blocking": True},
            "document_management": {"ready": True, "blocking": True},
            "ai_services": {"ready": False, "blocking": False},
        },
        "lifecycle_readiness": {"ready": True, "blocking_checks": []},
        "degraded_capabilities": ["rag", "ai_assistants", "vector_search"],
    }
    return {
        "plan": "platform_diagnostics_evidence",
        "timestamp_utc": "20260626T000000Z",
        "platform": diagnostics["platform"],
        "diagnostics": diagnostics,
        "summary": {"plan": "platform_diagnostics_summary"},
        "issues": {
            "plan": "platform_diagnostics_issues",
            "issues": [
                {"code": "capability_degraded:rag", "severity": "degraded", "scope": "degraded_capabilities", "name": "rag"}
            ],
        },
        "remediation": {
            "plan": "platform_diagnostics_remediation",
            "remediation": [
                {"issue_code": "capability_degraded:rag", "safe_to_automate": False, "destructive": False}
            ],
        },
        "catalog": {"plan": "platform_diagnostics_catalog"},
    }


def main() -> int:
    journey = build_platform_journey_from_diagnostics_evidence(sample_diagnostics_evidence())
    if journey["plan"] != "platform_product_journey":
        raise AssertionError("unexpected journey plan")
    if journey["journey_status"] != "complete_with_optional_degradation":
        raise AssertionError("AI degradation must not block the complete core/document journey")
    if journey["journey_complete"] is not True:
        raise AssertionError("core + document management should complete the journey")
    if journey["ai_services_blocking"] is not False:
        raise AssertionError("AI services must remain non-blocking")
    if journey["safe_to_run_without_ai"] is not True:
        raise AssertionError("platform should be safe to run without AI when core and document profiles are ready")
    if journey["evidence"]["source"] != "diagnostics_evidence_snapshot":
        raise AssertionError("journey must preserve diagnostics snapshot source")
    if journey.get("destructive_action_executed") is not False:
        raise AssertionError("journey projection must not report destructive actions")
    if journey.get("migration_executed") is not False:
        raise AssertionError("journey projection must not report migrations")
    if journey.get("downgrade_executed") is not False:
        raise AssertionError("journey projection must not report downgrades")

    print(json.dumps({"passed": True, "checked": ["platform-journey-evidence-projection"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
