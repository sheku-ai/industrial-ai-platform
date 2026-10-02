#!/usr/bin/env python3
"""Project a diagnostics evidence snapshot into the platform product journey."""

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

from app.services.platform_journey_evidence import (  # noqa: E402
    build_platform_journey_from_diagnostics_evidence,
)


def json_dump(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)


def read_json_object(file_path: str) -> Dict[str, Any]:
    payload = json.loads(Path(file_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("diagnostics_evidence_must_be_json_object")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build platform product journey from diagnostics evidence"
    )
    parser.add_argument("evidence_file")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = build_platform_journey_from_diagnostics_evidence(
            read_json_object(args.evidence_file)
        )
        print(json_dump(payload))
        return 0
    except Exception as exc:
        print(json_dump({"error": type(exc).__name__, "detail": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
