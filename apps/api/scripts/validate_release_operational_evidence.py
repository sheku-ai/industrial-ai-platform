from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.schemas.release_operational_evidence import OperationalEvidenceRequest
from app.services.release_operational_evidence_runtime import (
    build_operational_execution_key,
    evaluate_rollback_eligibility,
    evaluate_upgrade_readiness,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("upgrade", "rollback"))
    parser.add_argument("--backup-evidence-id", required=True, type=uuid.UUID)
    parser.add_argument("--execution-key")
    parser.add_argument("--correlation-id")
    parser.add_argument("--scope", choices=("platform", "organization"), default="platform")
    parser.add_argument("--organization-id", type=uuid.UUID)
    arguments = parser.parse_args()
    if arguments.scope == "organization" and arguments.organization_id is None:
        parser.error("--organization-id is required for organization scope")
    if SessionLocal is None:
        raise SystemExit("DATABASE_URL is required")

    root = Path(__file__).resolve().parents[3]
    manifest = json.loads((root / "release/manifest.json").read_text(encoding="utf-8"))
    edition = get_settings().platform_edition.strip().lower()
    if edition not in {"community", "enterprise"}:
        parser.error("PLATFORM_EDITION must be community or enterprise")
    edition_manifest = json.loads(
        (root / f"release/editions/{edition}.json").read_text(encoding="utf-8")
    )
    manifest["edition_manifest"] = edition_manifest
    alembic_config = Config(str(root / "apps/api/alembic.ini"))
    repository_heads = ScriptDirectory.from_config(alembic_config).get_heads()
    manifest["repository_heads"] = repository_heads
    evidence_type = "upgrade_readiness" if arguments.mode == "upgrade" else "rollback_eligibility"
    execution_key = build_operational_execution_key(
        evidence_type,
        edition,
        manifest["version"],
        arguments.execution_key or str(arguments.backup_evidence_id),
    )
    request = OperationalEvidenceRequest(
        scope=arguments.scope,
        organization_id=arguments.organization_id,
        release_version=manifest["version"],
        alembic_revision=manifest["alembic_head"],
        edition=edition,
        execution_key=execution_key,
        correlation_id=arguments.correlation_id or os.getenv("CORRELATION_ID"),
        backup_evidence_id=arguments.backup_evidence_id,
    )
    session = SessionLocal()
    try:
        if arguments.mode == "upgrade":
            result = evaluate_upgrade_readiness(session, request, manifest)
            successful = result.status == "passed"
        else:
            result = evaluate_rollback_eligibility(session, request, manifest)
            successful = result.status in {"passed", "requires_restore", "eligible_application_only"}
        session.commit()
        print(json.dumps(result.model_dump(mode="json"), sort_keys=True))
        return 0 if successful else 1
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
