#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.product_acceptance.classification import cli_exit_code  # noqa: E402
from app.services.product_acceptance.error_codes import error_payload  # noqa: E402
from app.services.product_acceptance.idempotency_evidence_runtime import (  # noqa: E402
    IdempotencyEvidenceAwareLocalProductAcceptanceRuntime,
)
from app.services.product_acceptance.reporting import write_report_atomic  # noqa: E402
from app.services.product_acceptance.runtime import RuntimeOptions  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local product acceptance through public platform APIs.")
    parser.add_argument("--api-base-url", default=os.getenv("API_BASE_URL", "http://127.0.0.1:8000/api"))
    parser.add_argument("--execution-key")
    parser.add_argument("--preserve", action="store_true")
    parser.add_argument("--reuse", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    parser.add_argument("--output")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print the detailed JSON summary, including blocker evidence.",
    )
    parser.add_argument(
        "--auth-email-env",
        default="ACCEPTANCE_AUTH_EMAIL",
        help="Environment variable containing the operator email or username.",
    )
    parser.add_argument(
        "--auth-password-env",
        default="ACCEPTANCE_AUTH_PASSWORD",
        help="Environment variable containing the operator password.",
    )
    parser.add_argument("--timeout", type=float, default=float(os.getenv("ACCEPTANCE_TIMEOUT", "20")))
    return parser.parse_args()


def build_console_summary(report: dict, output: str | None) -> dict:
    gate_summary = report.get("gate_summary") or {}
    return {
        "passed": report.get("passed"),
        "final_status": report.get("final_status"),
        "release_candidate_eligible": report.get("release_candidate_eligible"),
        "execution_key": report.get("execution_key"),
        "correlation_id": report.get("correlation_id"),
        "mandatory_gates": gate_summary.get("mandatory", 0),
        "mandatory_gates_passed": gate_summary.get("mandatory_passed", 0),
        "mandatory_capability_missing": gate_summary.get("mandatory_capability_missing", 0),
        "mandatory_failed": gate_summary.get("mandatory_failed", 0),
        "mandatory_blocked": gate_summary.get("mandatory_blocked", 0),
        "release_candidate_blockers": report.get("release_candidate_blockers") or [],
        "organization_id": (report.get("organization") or {}).get("id"),
        "document_record_id": (report.get("document") or {}).get("record_id"),
        "document_version_id": (report.get("document") or {}).get("version_id"),
        "storage_verified": (report.get("document") or {}).get("storage_verified"),
        "knowledge_indexed": (report.get("knowledge") or {}).get("knowledge_indexed"),
        "enterprise_search_visible": (report.get("search") or {}).get("enterprise_search_visible"),
        "assistant_id": (report.get("assistant") or {}).get("assistant_id"),
        "warnings": report.get("warnings") or [],
        "blockers": report.get("blockers") or [],
        "output": output,
    }


def print_concise_summary(summary: dict) -> None:
    status = str(summary.get("final_status") or ("PASSED" if summary.get("passed") else "FAILED"))
    eligible = "YES" if summary.get("release_candidate_eligible") else "NO"
    mandatory = int(summary.get("mandatory_gates") or 0)
    passed = int(summary.get("mandatory_gates_passed") or 0)
    failed = int(summary.get("mandatory_failed") or 0)
    blocked = int(summary.get("mandatory_blocked") or 0)
    missing = int(summary.get("mandatory_capability_missing") or 0)

    print(f"PRODUCT ACCEPTANCE: {status}")
    print(f"Mandatory gates: {passed}/{mandatory} passed")
    print(f"Failures: {failed} | Blocked: {blocked} | Missing capabilities: {missing}")
    print(f"Release candidate eligible: {eligible}")
    print(f"Warnings: {len(summary.get('warnings') or [])}")

    release_blockers = summary.get("release_candidate_blockers") or []
    runtime_blockers = summary.get("blockers") or []
    if release_blockers or runtime_blockers:
        print("Problems:")
        emitted: set[tuple[str, str, str]] = set()
        for blocker in release_blockers:
            if not isinstance(blocker, dict):
                continue
            phase = str(blocker.get("phase_code") or "runtime")
            gate = str(blocker.get("gate_code") or "unspecified")
            error_code = str(blocker.get("error_code") or blocker.get("code") or "UNCLASSIFIED")
            key = (phase, gate, error_code)
            if key in emitted:
                continue
            emitted.add(key)
            print(f"- {phase}/{gate}: {error_code}")
        release_codes = {key[2] for key in emitted}
        for blocker in runtime_blockers:
            if not isinstance(blocker, dict):
                continue
            error_code = str(blocker.get("error_code") or blocker.get("code") or "UNCLASSIFIED")
            if error_code in release_codes:
                continue
            key = ("runtime", "blocker", error_code)
            if key in emitted:
                continue
            emitted.add(key)
            print(f"- runtime: {error_code}")

    print(f"Full report: {summary.get('output') or 'not written'}")


def main() -> int:
    args = parse_args()
    if (args.reuse or args.cleanup) and not args.execution_key:
        print(json.dumps({"passed": False, "error": "execution_key_required_for_reuse_or_cleanup"}))
        return cli_exit_code({}, invalid_args=True)

    auth_email = os.getenv(args.auth_email_env)
    auth_password = os.getenv(args.auth_password_env)
    if not auth_email or not auth_password:
        print(
            json.dumps(
                {
                    "passed": False,
                    "error": "acceptance_authentication_credentials_not_configured",
                    "required_environment": [args.auth_email_env, args.auth_password_env],
                }
            )
        )
        return cli_exit_code({}, invalid_args=True)

    runtime = IdempotencyEvidenceAwareLocalProductAcceptanceRuntime(
        RuntimeOptions(
            api_base_url=args.api_base_url,
            auth_email=auth_email,
            auth_password=auth_password,
            execution_key=args.execution_key,
            preserve=args.preserve,
            reuse=args.reuse,
            cleanup=args.cleanup,
            timeout=args.timeout,
        )
    )
    report = runtime.run()
    report_write_failed = False
    if args.output:
        try:
            write_report_atomic(args.output, report)
        except OSError as exc:
            report_write_failed = True
            report.setdefault("blockers", []).append(
                {
                    **error_payload("REPORT_WRITE_FAILED"),
                    "details": {"output": args.output, "error": str(exc)},
                }
            )

    summary = build_console_summary(report, args.output)
    if args.verbose:
        print(json.dumps(summary, indent=2, sort_keys=True, default=str))
        print()
    print_concise_summary(summary)
    return cli_exit_code(report, persistence_or_report_failed=report_write_failed)


if __name__ == "__main__":
    raise SystemExit(main())
