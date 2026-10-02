from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.conversation_intent_model import ConversationIntentModel
from app.repositories.conversation_intent_model import ConversationIntentModelRepository
from app.services.community_intent_model_artifact import (
    COMMUNITY_INTENT_ARTIFACT_REFERENCE,
    COMMUNITY_INTENT_MANIFEST_NAME,
    artifact_hash,
    load_and_validate_artifact_manifest,
    verify_setfit_artifact,
)

COMMUNITY_ACTIVE_MODEL_CONSTRAINT = "uq_ai_conversation_intent_models_active_community_family"


class CommunityIntentModelBootstrapConflict(RuntimeError):
    """Raised when bootstrap would silently replace Community model authority."""


@dataclass(frozen=True)
class CommunityIntentModelBootstrapResult:
    model: ConversationIntentModel
    reused: bool


def _api_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _integrity_constraint_name(exc: IntegrityError) -> str | None:
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def _validate_existing_model(
    record: ConversationIntentModel,
    *,
    manifest: dict[str, Any],
) -> None:
    expected = {
        "organization_id": None,
        "organization_node_id": None,
        "ownership_scope": "global",
        "scope_type": "community",
        "data_origin": "operational",
        "model_family": manifest["model_family"],
        "provider": manifest["provider"],
        "model_version": manifest["model_version"],
        "model_status": "active",
        "artifact_reference": manifest["artifact_reference"],
        "artifact_hash": manifest["artifact_hash"],
    }
    mismatched = [
        field_name
        for field_name, expected_value in expected.items()
        if getattr(record, field_name) != expected_value
    ]
    if mismatched:
        raise CommunityIntentModelBootstrapConflict(
            "existing Community intent model conflicts with packaged artifact: "
            + ", ".join(mismatched)
        )


def bootstrap_community_intent_model(
    session: Session,
    *,
    artifact_directory: Path | None = None,
) -> CommunityIntentModelBootstrapResult:
    artifact_root = artifact_directory or (_api_root() / COMMUNITY_INTENT_ARTIFACT_REFERENCE)
    manifest = load_and_validate_artifact_manifest(artifact_root / COMMUNITY_INTENT_MANIFEST_NAME)
    verify_setfit_artifact(artifact_root)
    calculated_artifact_hash = artifact_hash(artifact_root)
    if calculated_artifact_hash != manifest["artifact_hash"]:
        raise ValueError("packaged Community intent model artifact hash is inconsistent")

    repository = ConversationIntentModelRepository(session)
    version_records = repository.get_community_models_by_version(
        model_family=manifest["model_family"],
        model_version=manifest["model_version"],
    )
    if len(version_records) > 1:
        raise CommunityIntentModelBootstrapConflict(
            "multiple Community intent model records exist for the packaged version"
        )
    if version_records:
        _validate_existing_model(version_records[0], manifest=manifest)
        return CommunityIntentModelBootstrapResult(model=version_records[0], reused=True)

    active = repository.get_active_community_model(manifest["model_family"])
    if active is not None:
        raise CommunityIntentModelBootstrapConflict(
            "a different Community intent model is already active; automatic replacement is disabled"
        )

    try:
        with session.begin_nested():
            created = repository.create_community_model(
                model_family=manifest["model_family"],
                provider=manifest["provider"],
                model_version=manifest["model_version"],
                artifact_reference=manifest["artifact_reference"],
                artifact_hash=manifest["artifact_hash"],
                model_metadata={
                    "dataset_version": manifest["dataset_version"],
                    "dataset_hash": manifest["dataset_hash"],
                    "base_model": manifest["base_model"],
                    "build_configuration_hash": manifest["build_configuration_hash"],
                    "intent_catalog": list(manifest["intent_catalog"]),
                    "languages": list(manifest["languages"]),
                    "offline_runtime": True,
                },
            )
        return CommunityIntentModelBootstrapResult(model=created, reused=False)
    except IntegrityError as exc:
        if _integrity_constraint_name(exc) != COMMUNITY_ACTIVE_MODEL_CONSTRAINT:
            raise
        winner = repository.get_active_community_model(manifest["model_family"])
        if winner is None:
            raise
        _validate_existing_model(winner, manifest=manifest)
        return CommunityIntentModelBootstrapResult(model=winner, reused=True)
