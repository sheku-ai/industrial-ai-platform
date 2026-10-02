#!/usr/bin/env python3
"""CLI wrapper for the platform product journey."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
DEFAULT_EVIDENCE_DIR = ROOT / "runtime" / "evidence" / "platform-journey"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.platform_journey import build_platform_journey  # noqa: E402
from app.services.platform_journey_closeout import (  # noqa: E402
    build_platform_journey_closeout_package_from_projections,
)
from app.services.platform_journey_closeout_checklist import (  # noqa: E402
    build_platform_journey_closeout_checklist_from_package,
)
from app.services.platform_journey_projection import build_platform_journey_terminal_projections  # noqa: E402
from app.services.platform_journey_views import (  # noqa: E402
    build_platform_journey_actions_from_journey,
    build_platform_journey_steps_from_journey,
    build_platform_journey_summary_from_journey,
)


def json_dump(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)


def evidence_filename(timestamp_utc: str) -> str:
    safe_timestamp = re.sub(r"[^0-9TZ]", "", timestamp_utc)
    return f"journey_{safe_timestamp}.json"


def write_journey_evidence(payload: Dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / evidence_filename(payload["timestamp_utc"])
    output_path.write_text(json_dump(payload) + "\n", encoding="utf-8")
    return output_path


def project_cli_view(payload: Dict[str, Any], args: argparse.Namespace) -> Dict[str, Any]:
    if args.summary:
        return build_platform_journey_summary_from_journey(payload)
    if args.steps:
        return build_platform_journey_steps_from_journey(payload)
    if args.actions:
        return build_platform_journey_actions_from_journey(payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Industrial AI Platform product journey command")
    parser.add_argument("--alembic-config", default=None)
    parser.add_argument("--timeout-s", type=int, default=30)
    parser.add_argument("--target-revision", default=None)
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--steps", action="store_true")
    parser.add_argument("--actions", action="store_true")
    parser.add_argument("--bundle", action="store_true")
    parser.add_argument("--handoff", action="store_true")
    parser.add_argument("--operator-console", action="store_true")
    parser.add_argument("--readiness-matrix", action="store_true")
    parser.add_argument("--validation-plan", action="store_true")
    parser.add_argument("--acceptance", action="store_true")
    parser.add_argument("--release-readiness", action="store_true")
    parser.add_argument("--completion-report", action="store_true")
    parser.add_argument("--closeout-package", action="store_true")
    parser.add_argument("--closeout-checklist", action="store_true")
    parser.add_argument("--evidence-limit", type=int, default=5)
    parser.add_argument("--write-evidence", action="store_true")
    parser.add_argument("--output", default=str(DEFAULT_EVIDENCE_DIR))
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    selected_views = [
        args.summary,
        args.steps,
        args.actions,
        args.bundle,
        args.handoff,
        args.operator_console,
        args.readiness_matrix,
        args.validation_plan,
        args.acceptance,
        args.release_readiness,
        args.completion_report,
        args.closeout_package,
        args.closeout_checklist,
    ]
    if sum(1 for selected in selected_views if selected) > 1:
        print(json_dump({"error": "ValueError", "detail": "select_only_one_journey_view"}))
        return 1
    operator_projection_selected = bool(
        args.bundle or args.handoff or args.operator_console or args.readiness_matrix
        or args.validation_plan or args.acceptance or args.release_readiness
        or args.completion_report or args.closeout_package or args.closeout_checklist
    )
    if args.write_evidence and operator_projection_selected:
        print(json_dump({"error": "ValueError", "detail": "select_write_evidence_or_operator_projection"}))
        return 1
    try:
        if operator_projection_selected:
            projections = build_platform_journey_terminal_projections(
                alembic_config=args.alembic_config,
                timeout_s=args.timeout_s,
                target_revision=args.target_revision,
                evidence_limit=args.evidence_limit,
            )
            if args.bundle:
                payload = projections["bundle"]
            elif args.operator_console:
                payload = projections["operator_console"]
            elif args.readiness_matrix:
                payload = projections["readiness_matrix"]
            elif args.validation_plan:
                payload = projections["validation_plan"]
            elif args.acceptance:
                payload = projections["acceptance"]
            elif args.release_readiness:
                payload = projections["release_readiness"]
            elif args.completion_report:
                payload = projections["completion_report"]
            elif args.closeout_package:
                payload = build_platform_journey_closeout_package_from_projections(projections)
            elif args.closeout_checklist:
                closeout_package = build_platform_journey_closeout_package_from_projections(projections)
                payload = build_platform_journey_closeout_checklist_from_package(closeout_package)
            else:
                payload = projections["handoff"]
        else:
            journey = build_platform_journey(
                alembic_config=args.alembic_config,
                timeout_s=args.timeout_s,
                target_revision=args.target_revision,
            )
            if args.write_evidence:
                output_path = write_journey_evidence(journey, Path(args.output))
                payload = {
                    "plan": "platform_product_journey_evidence_written",
                    "evidence_path": str(output_path),
                    "timestamp_utc": journey["timestamp_utc"],
                    "destructive_action_executed": False,
                    "migration_executed": False,
                    "downgrade_executed": False,
                }
            else:
                payload = project_cli_view(journey, args)
        print(json_dump(payload))
        return 0
    except Exception as exc:
        print(json_dump({"error": type(exc).__name__, "detail": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
