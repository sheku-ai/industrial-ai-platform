#!/usr/bin/env python3
"""Fast structural contract for platform journey evidence store views."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import sys


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.platform_journey_evidence_store import (  # noqa: E402
    get_latest_platform_journey_evidence,
    list_platform_journey_evidence,
)


def write_sample(path: Path, *, timestamp: str, status: str) -> None:
    path.write_text(
        json.dumps(
            {
                "plan": "platform_product_journey",
                "journey_schema_version": "1",
                "timestamp_utc": timestamp,
                "platform": {"name": "Industrial AI Platform", "version": "v1.3.1"},
                "journey_status": status,
                "journey_complete": True,
                "safe_to_run_without_ai": True,
                "ai_services_blocking": False,
                "blocking_issue_count": 0,
                "degraded_capabilities": ["rag"],
                "runtime_profiles": {
                    "core": {"ready": True, "blocking": True},
                    "document_management": {"ready": True, "blocking": True},
                    "ai_services": {"ready": False, "blocking": False},
                },
                "steps": [],
                "operator_next_actions": [],
                "destructive_action_executed": False,
                "migration_executed": False,
                "downgrade_executed": False,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def require_keys(payload: dict[str, Any], keys: set[str], context: str) -> None:
    missing = sorted(keys - set(payload))
    if missing:
        raise AssertionError(f"{context} missing keys: {missing}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="platform-journey-store-") as tmpdir:
        root = Path(tmpdir)
        older = root / "journey_20260626T000000Z.json"
        latest = root / "journey_20260626T010000Z.json"
        ignored = root / "diagnostics_20260626T010000Z.json"
        write_sample(older, timestamp="20260626T000000Z", status="complete")
        write_sample(latest, timestamp="20260626T010000Z", status="complete_with_optional_degradation")
        ignored.write_text("{}", encoding="utf-8")

        index = list_platform_journey_evidence(evidence_dir=tmpdir, limit=20)
        require_keys(
            index,
            {
                "destructive_action_executed",
                "downgrade_executed",
                "evidence_dir",
                "exists",
                "migration_executed",
                "plan",
                "returned_count",
                "snapshot_count",
                "snapshots",
            },
            "journey_evidence_index",
        )
        if index["plan"] != "platform_product_journey_evidence_index":
            raise AssertionError("unexpected evidence index plan")
        if index["snapshot_count"] != 2 or index["returned_count"] != 2:
            raise AssertionError("evidence index must include only journey evidence files")
        if index["snapshots"][0]["timestamp_utc"] != "20260626T010000Z":
            raise AssertionError("evidence index must return newest snapshot first")
        if index["snapshots"][0]["valid_json"] is not True:
            raise AssertionError("evidence index must parse valid JSON snapshots")
        if "payload" in index["snapshots"][0]:
            raise AssertionError("evidence index must not inline full payloads")

        latest_payload = get_latest_platform_journey_evidence(evidence_dir=tmpdir)
        require_keys(
            latest_payload,
            {
                "destructive_action_executed",
                "downgrade_executed",
                "evidence_dir",
                "found",
                "migration_executed",
                "plan",
                "snapshot",
            },
            "journey_evidence_latest",
        )
        if latest_payload["plan"] != "platform_product_journey_evidence_latest":
            raise AssertionError("unexpected evidence latest plan")
        if latest_payload["found"] is not True:
            raise AssertionError("latest evidence must be found")
        snapshot = latest_payload["snapshot"]
        if snapshot["timestamp_utc"] != "20260626T010000Z":
            raise AssertionError("latest evidence must return newest snapshot")
        if not isinstance(snapshot.get("payload"), dict):
            raise AssertionError("latest evidence must include full payload")
        if snapshot["payload"]["ai_services_blocking"] is not False:
            raise AssertionError("latest evidence must preserve AI non-blocking contract")

        empty_dir = root / "empty"
        empty_dir.mkdir()
        empty = get_latest_platform_journey_evidence(evidence_dir=str(empty_dir))
        if empty["found"] is not False or empty["snapshot"] is not None:
            raise AssertionError("empty evidence directory must return found=false")

        for payload in (index, latest_payload, empty):
            if payload.get("destructive_action_executed") is not False:
                raise AssertionError("evidence store view must not report destructive actions")
            if payload.get("migration_executed") is not False:
                raise AssertionError("evidence store view must not report migrations")
            if payload.get("downgrade_executed") is not False:
                raise AssertionError("evidence store view must not report downgrades")

    print(json.dumps({"passed": True, "checked": ["platform-journey-evidence-store"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
