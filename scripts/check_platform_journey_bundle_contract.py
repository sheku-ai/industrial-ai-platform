#!/usr/bin/env python3
"""Fast structural contract for the platform journey operator bundle."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.platform_journey_bundle import build_platform_journey_bundle  # noqa: E402


REQUIRED_BUNDLE_KEYS = {
    "ai_services_blocking",
    "blocking_issue_count",
    "bundle_schema_version",
    "degraded_capabilities",
    "destructive_action_executed",
    "downgrade_executed",
    "evidence_store",
    "journey",
    "journey_complete",
    "journey_status",
    "migration_executed",
    "operator",
    "plan",
    "platform",
    "safe_to_run_without_ai",
    "timestamp_utc",
    "views",
}

REQUIRED_CONSISTENCY_KEYS = {
    "compared_fields",
    "destructive_action_executed",
    "downgrade_executed",
    "evidence_available",
    "latest_evidence_timestamp_utc",
    "matches_live_journey",
    "migration_executed",
    "mismatched_fields",
    "operator_message",
    "status",
}


def require_keys(payload: dict[str, Any], keys: set[str], context: str) -> None:
    missing = sorted(keys - set(payload))
    if missing:
        raise AssertionError(f"{context} missing keys: {missing}")


def main() -> int:
    bundle = build_platform_journey_bundle(evidence_limit=3)
    require_keys(bundle, REQUIRED_BUNDLE_KEYS, "journey_bundle")

    if bundle["plan"] != "platform_product_journey_bundle":
        raise AssertionError("unexpected bundle plan")
    if bundle["bundle_schema_version"] != "1":
        raise AssertionError("unexpected bundle schema version")
    if bundle["ai_services_blocking"] is not False:
        raise AssertionError("bundle must preserve AI non-blocking contract")
    if bundle["journey"].get("plan") != "platform_product_journey":
        raise AssertionError("bundle must include the full journey")
    if bundle["journey_status"] != bundle["journey"].get("journey_status"):
        raise AssertionError("bundle journey status must match full journey")
    if bundle["journey_complete"] != bundle["journey"].get("journey_complete"):
        raise AssertionError("bundle journey_complete must match full journey")
    if bundle["safe_to_run_without_ai"] != bundle["journey"].get("safe_to_run_without_ai"):
        raise AssertionError("bundle no-AI readiness must match full journey")

    operator = bundle["operator"]
    require_keys(
        operator,
        {
            "evidence_available",
            "evidence_consistency_status",
            "latest_evidence_timestamp_utc",
            "next_action_count",
            "ready_for_manual_validation",
        },
        "bundle_operator",
    )
    expected_ready = bool(bundle["journey_complete"] and bundle["blocking_issue_count"] == 0)
    if operator["ready_for_manual_validation"] != expected_ready:
        raise AssertionError("operator readiness must derive from journey completion and blocking issues")

    views = bundle["views"]
    require_keys(views, {"actions", "steps", "summary"}, "bundle_views")
    if views["summary"].get("plan") != "platform_product_journey_summary":
        raise AssertionError("bundle must include summary view")
    if views["steps"].get("plan") != "platform_product_journey_steps":
        raise AssertionError("bundle must include steps view")
    if views["actions"].get("plan") != "platform_product_journey_actions":
        raise AssertionError("bundle must include actions view")
    if operator["next_action_count"] != views["actions"].get("action_count"):
        raise AssertionError("operator next action count must match actions view")

    evidence_store = bundle["evidence_store"]
    require_keys(evidence_store, {"consistency", "index", "latest"}, "bundle_evidence_store")
    if evidence_store["index"].get("plan") != "platform_product_journey_evidence_index":
        raise AssertionError("bundle must include journey evidence index")
    if evidence_store["latest"].get("plan") != "platform_product_journey_evidence_latest":
        raise AssertionError("bundle must include latest journey evidence")

    consistency = evidence_store["consistency"]
    require_keys(consistency, REQUIRED_CONSISTENCY_KEYS, "bundle_evidence_consistency")
    if consistency["status"] not in {"in_sync", "missing", "out_of_sync"}:
        raise AssertionError("unexpected evidence consistency status")
    if operator["evidence_consistency_status"] != consistency["status"]:
        raise AssertionError("operator consistency status must match evidence store consistency")
    if consistency["destructive_action_executed"] is not False:
        raise AssertionError("consistency view must not report destructive actions")
    if consistency["migration_executed"] is not False:
        raise AssertionError("consistency view must not report migrations")
    if consistency["downgrade_executed"] is not False:
        raise AssertionError("consistency view must not report downgrades")

    if bundle.get("destructive_action_executed") is not False:
        raise AssertionError("bundle must not report destructive actions")
    if bundle.get("migration_executed") is not False:
        raise AssertionError("bundle must not report migrations")
    if bundle.get("downgrade_executed") is not False:
        raise AssertionError("bundle must not report downgrades")

    print(json.dumps({"passed": True, "checked": ["platform-journey-bundle"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
