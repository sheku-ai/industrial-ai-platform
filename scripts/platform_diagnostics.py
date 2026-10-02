#!/usr/bin/env python3
"""CLI wrapper for the shared platform diagnostics service."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
DEFAULT_EVIDENCE_DIR = ROOT / "runtime" / "evidence" / "platform-diagnostics"
SECRET_KEY_PATTERNS = ("SECRET", "TOKEN", "PASSWORD", "API_KEY", "ACCESS_KEY")
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.platform_diagnostics import (  # noqa: E402
    build_platform_diagnostics,
    build_platform_diagnostics_catalog,
    build_platform_diagnostics_issues,
    build_platform_diagnostics_remediation,
    build_platform_diagnostics_summary,
)


def json_dump(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)


def compact_utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def evidence_filename(timestamp_utc: str) -> str:
    safe_timestamp = re.sub(r"[^0-9TZ]", "", timestamp_utc)
    return f"diagnostics_{safe_timestamp}.json"


def environment_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    diagnostics = payload["diagnostics"]
    return {
        "critical_services_ready": all(
            bool(service.get("ready")) for service in diagnostics["critical_services"].values()
        ),
        "optional_services_ready": all(
            bool(service.get("ready")) for service in diagnostics["optional_services"].values()
        ),
        "overall_status": diagnostics["overall_status"],
        "runtime_profiles": {
            name: {
                "ready": bool(profile.get("ready")),
                "blocking": bool(profile.get("blocking")),
            }
            for name, profile in diagnostics["runtime_profiles"].items()
        },
        "degraded_capabilities": list(diagnostics["degraded_capabilities"]),
    }


def build_evidence_payload(
    *,
    alembic_config: Optional[str],
    timeout_s: int,
    target_revision: Optional[str],
    timestamp_utc: str,
) -> Dict[str, Any]:
    diagnostics = build_platform_diagnostics(
        alembic_config=alembic_config,
        timeout_s=timeout_s,
        target_revision=target_revision,
    )
    payload: Dict[str, Any] = {
        "plan": "platform_diagnostics_evidence",
        "evidence_schema_version": "1",
        "timestamp_utc": timestamp_utc,
        "generated_by": "scripts/platform_diagnostics.py",
        "platform": diagnostics["platform"],
        "lifecycle": {
            "migrations": diagnostics["migrations"],
            "readiness": diagnostics["lifecycle_readiness"],
        },
        "diagnostics": diagnostics,
        "summary": build_platform_diagnostics_summary(
            alembic_config=alembic_config,
            timeout_s=timeout_s,
            target_revision=target_revision,
        ),
        "issues": build_platform_diagnostics_issues(
            alembic_config=alembic_config,
            timeout_s=timeout_s,
            target_revision=target_revision,
        ),
        "remediation": build_platform_diagnostics_remediation(
            alembic_config=alembic_config,
            timeout_s=timeout_s,
            target_revision=target_revision,
        ),
        "catalog": build_platform_diagnostics_catalog(),
        "runtime_profiles": diagnostics["runtime_profiles"],
        "critical_services": diagnostics["critical_services"],
        "optional_services": diagnostics["optional_services"],
        "degraded_capabilities": diagnostics["degraded_capabilities"],
        "destructive_action_executed": False,
        "migration_executed": False,
        "downgrade_executed": False,
    }
    payload["environment_summary"] = environment_summary(payload)
    return payload


def assert_no_secret_values(payload: Any, path: str = "") -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_path = f"{path}.{key}" if path else str(key)
            key_upper = str(key).upper()
            if isinstance(value, str) and any(pattern in key_upper for pattern in SECRET_KEY_PATTERNS):
                if value and value != "<redacted>":
                    raise ValueError(f"evidence_contains_secret_value:{key_path}")
            assert_no_secret_values(value, key_path)
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            assert_no_secret_values(item, f"{path}[{index}]")


def write_evidence_file(payload: Dict[str, Any], output_dir: Path) -> Path:
    assert_no_secret_values(payload)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / evidence_filename(payload["timestamp_utc"])
    output_path.write_text(json_dump(payload) + "\n", encoding="utf-8")
    return output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Industrial AI Platform diagnostics command")
    parser.add_argument("--alembic-config", default=None)
    parser.add_argument("--timeout-s", type=int, default=30)
    parser.add_argument("--target-revision", default=None)
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--issues", action="store_true")
    parser.add_argument("--remediation", action="store_true")
    parser.add_argument("--catalog", action="store_true")
    parser.add_argument("--write-evidence", action="store_true")
    parser.add_argument("--output", default=str(DEFAULT_EVIDENCE_DIR))
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.write_evidence:
            timestamp_utc = compact_utc_timestamp()
            payload = build_evidence_payload(
                alembic_config=args.alembic_config,
                timeout_s=args.timeout_s,
                target_revision=args.target_revision,
                timestamp_utc=timestamp_utc,
            )
            output_path = write_evidence_file(payload, Path(args.output))
            payload = {
                "plan": "platform_diagnostics_evidence_written",
                "evidence_path": str(output_path),
                "timestamp_utc": timestamp_utc,
                "destructive_action_executed": False,
                "migration_executed": False,
                "downgrade_executed": False,
            }
        elif args.catalog:
            payload = build_platform_diagnostics_catalog()
        else:
            if args.remediation:
                builder = build_platform_diagnostics_remediation
            elif args.issues:
                builder = build_platform_diagnostics_issues
            elif args.summary:
                builder = build_platform_diagnostics_summary
            else:
                builder = build_platform_diagnostics
            payload = builder(
                alembic_config=args.alembic_config,
                timeout_s=args.timeout_s,
                target_revision=args.target_revision,
            )
        print(json_dump(payload))
        return 0
    except Exception as exc:
        print(json_dump({"error": type(exc).__name__, "detail": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())