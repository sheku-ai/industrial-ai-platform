"""Operator bundle for the complete platform product journey.

The bundle combines the live journey, lightweight views and evidence-store
state into a single non-destructive response for operator consoles and smoke
checks. It reuses existing builders and does not execute migrations, downgrades,
AI calls, vector calls or remediation actions.
"""

from __future__ import annotations

from typing import Any

from app.services.platform_journey import build_platform_journey
from app.services.platform_journey_evidence_store import (
    get_latest_platform_journey_evidence,
    list_platform_journey_evidence,
)
from app.services.platform_journey_views import (
    build_platform_journey_actions_from_journey,
    build_platform_journey_steps_from_journey,
    build_platform_journey_summary_from_journey,
)

BUNDLE_SCHEMA_VERSION = "1"


def _latest_snapshot_payload(latest_evidence: dict[str, Any]) -> dict[str, Any]:
    snapshot = latest_evidence.get("snapshot") or {}
    if not isinstance(snapshot, dict):
        return {}
    payload = snapshot.get("payload")
    if isinstance(payload, dict):
        return payload
    return snapshot


def build_evidence_consistency(
    *,
    journey: dict[str, Any],
    latest_evidence: dict[str, Any],
) -> dict[str, Any]:
    """Compare live journey status with latest stored evidence metadata."""

    evidence_available = bool(latest_evidence.get("found"))
    latest_snapshot = latest_evidence.get("snapshot") or {}
    latest_payload = _latest_snapshot_payload(latest_evidence)
    latest_timestamp = latest_snapshot.get("timestamp_utc") if isinstance(latest_snapshot, dict) else None

    compared_fields = {
        "journey_status": {
            "live": journey.get("journey_status"),
            "evidence": latest_payload.get("journey_status"),
        },
        "journey_complete": {
            "live": journey.get("journey_complete"),
            "evidence": latest_payload.get("journey_complete"),
        },
        "safe_to_run_without_ai": {
            "live": journey.get("safe_to_run_without_ai"),
            "evidence": latest_payload.get("safe_to_run_without_ai"),
        },
        "blocking_issue_count": {
            "live": journey.get("blocking_issue_count"),
            "evidence": latest_payload.get("blocking_issue_count"),
        },
        "ai_services_blocking": {
            "live": journey.get("ai_services_blocking"),
            "evidence": latest_payload.get("ai_services_blocking"),
        },
    }
    mismatches = [name for name, values in compared_fields.items() if values["live"] != values["evidence"]]

    if not evidence_available:
        status = "missing"
        operator_message = "No platform journey evidence snapshot is available."
    elif mismatches:
        status = "out_of_sync"
        operator_message = "Latest platform journey evidence does not match live journey state."
    else:
        status = "in_sync"
        operator_message = "Latest platform journey evidence matches live journey state."

    return {
        "status": status,
        "evidence_available": evidence_available,
        "latest_evidence_timestamp_utc": latest_timestamp,
        "matches_live_journey": bool(evidence_available and not mismatches),
        "mismatched_fields": mismatches,
        "compared_fields": compared_fields,
        "operator_message": operator_message,
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }


def build_platform_journey_bundle(
    *,
    alembic_config: str | None = None,
    timeout_s: int = 30,
    target_revision: str | None = None,
    evidence_limit: int = 5,
) -> dict[str, Any]:
    """Build a complete operator-facing platform journey bundle."""

    journey = build_platform_journey(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
    )
    summary = build_platform_journey_summary_from_journey(journey)
    steps = build_platform_journey_steps_from_journey(journey)
    actions = build_platform_journey_actions_from_journey(journey)
    evidence_index = list_platform_journey_evidence(limit=evidence_limit)
    latest_evidence = get_latest_platform_journey_evidence()
    evidence_consistency = build_evidence_consistency(
        journey=journey,
        latest_evidence=latest_evidence,
    )

    return {
        "plan": "platform_product_journey_bundle",
        "bundle_schema_version": BUNDLE_SCHEMA_VERSION,
        "timestamp_utc": journey["timestamp_utc"],
        "platform": journey["platform"],
        "journey_status": journey["journey_status"],
        "journey_complete": journey["journey_complete"],
        "safe_to_run_without_ai": journey["safe_to_run_without_ai"],
        "ai_services_blocking": False,
        "blocking_issue_count": journey["blocking_issue_count"],
        "degraded_capabilities": journey["degraded_capabilities"],
        "operator": {
            "ready_for_manual_validation": bool(journey["journey_complete"] and journey["blocking_issue_count"] == 0),
            "evidence_available": evidence_consistency["evidence_available"],
            "evidence_consistency_status": evidence_consistency["status"],
            "latest_evidence_timestamp_utc": evidence_consistency["latest_evidence_timestamp_utc"],
            "next_action_count": actions["action_count"],
        },
        "views": {
            "summary": summary,
            "steps": steps,
            "actions": actions,
        },
        "evidence_store": {
            "index": evidence_index,
            "latest": latest_evidence,
            "consistency": evidence_consistency,
        },
        "journey": journey,
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }
