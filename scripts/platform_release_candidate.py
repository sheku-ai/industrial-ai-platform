#!/usr/bin/env python3
"""CLI wrapper for non-executing Release Candidate readiness views."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.platform_release_candidate import (  # noqa: E402
    build_release_artifact_catalog,
    build_release_candidate_checklist,
    build_release_candidate_ci_contract,
    build_release_candidate_command_catalog,
    build_release_candidate_evidence,
    build_release_candidate_gates,
    build_release_candidate_manifest,
    build_release_candidate_readiness,
    build_release_compatibility_matrix,
    build_release_contract,
    build_release_summary,
)


def json_dump(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Industrial AI Platform Release Candidate readiness command")
    parser.add_argument("--alembic-config", default=None)
    parser.add_argument("--timeout-s", type=int, default=30)
    parser.add_argument("--target-revision", default=None)
    parser.add_argument("--evidence-limit", type=int, default=5)
    parser.add_argument("--commands", action="store_true")
    parser.add_argument("--evidence", action="store_true")
    parser.add_argument("--gates", action="store_true")
    parser.add_argument("--checklist", action="store_true")
    parser.add_argument("--ci-contract", action="store_true")
    parser.add_argument("--manifest", action="store_true")
    parser.add_argument("--release-contract", action="store_true")
    parser.add_argument("--release-summary", action="store_true")
    parser.add_argument("--compatibility", action="store_true")
    parser.add_argument("--artifacts", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    selected_views = [
        args.commands,
        args.evidence,
        args.gates,
        args.checklist,
        args.ci_contract,
        args.manifest,
        args.release_contract,
        args.release_summary,
        args.compatibility,
        args.artifacts,
    ]
    if sum(1 for selected in selected_views if selected) > 1:
        print(json_dump({"error": "ValueError", "detail": "select_only_one_release_candidate_view"}))
        return 1
    try:
        if args.commands:
            payload = build_release_candidate_command_catalog()
        elif args.evidence:
            payload = build_release_candidate_evidence(
                alembic_config=args.alembic_config,
                timeout_s=args.timeout_s,
                target_revision=args.target_revision,
                evidence_limit=args.evidence_limit,
            )
        elif args.gates:
            payload = build_release_candidate_gates(
                alembic_config=args.alembic_config,
                timeout_s=args.timeout_s,
                target_revision=args.target_revision,
                evidence_limit=args.evidence_limit,
            )
        elif args.checklist:
            payload = build_release_candidate_checklist(
                alembic_config=args.alembic_config,
                timeout_s=args.timeout_s,
                target_revision=args.target_revision,
                evidence_limit=args.evidence_limit,
            )
        elif args.ci_contract:
            payload = build_release_candidate_ci_contract(
                alembic_config=args.alembic_config,
                timeout_s=args.timeout_s,
                target_revision=args.target_revision,
                evidence_limit=args.evidence_limit,
            )
        elif args.manifest:
            payload = build_release_candidate_manifest(
                alembic_config=args.alembic_config,
                timeout_s=args.timeout_s,
                target_revision=args.target_revision,
                evidence_limit=args.evidence_limit,
            )
        elif args.release_contract:
            payload = build_release_contract(
                alembic_config=args.alembic_config,
                timeout_s=args.timeout_s,
                target_revision=args.target_revision,
                evidence_limit=args.evidence_limit,
            )
        elif args.release_summary:
            payload = build_release_summary(
                alembic_config=args.alembic_config,
                timeout_s=args.timeout_s,
                target_revision=args.target_revision,
                evidence_limit=args.evidence_limit,
            )
        elif args.compatibility:
            payload = build_release_compatibility_matrix(
                alembic_config=args.alembic_config,
                timeout_s=args.timeout_s,
                target_revision=args.target_revision,
                evidence_limit=args.evidence_limit,
            )
        elif args.artifacts:
            payload = build_release_artifact_catalog(
                alembic_config=args.alembic_config,
                timeout_s=args.timeout_s,
                target_revision=args.target_revision,
                evidence_limit=args.evidence_limit,
            )
        else:
            payload = build_release_candidate_readiness(
                alembic_config=args.alembic_config,
                timeout_s=args.timeout_s,
                target_revision=args.target_revision,
                evidence_limit=args.evidence_limit,
            )
        print(json_dump(payload))
        return 0
    except Exception as exc:
        print(json_dump({"error": type(exc).__name__, "detail": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
