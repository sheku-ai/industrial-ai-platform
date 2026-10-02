from __future__ import annotations

from sqlalchemy import select

from app.models.ingestion import IngestionPipelineProfile
from app.services.ingestion_adapter_resolver import AdapterPolicy, DeploymentEdition
from app.services.ingestion_configuration import IngestionPipelineProfileSnapshot


class SqlAlchemyIngestionProfileRepository:
    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def get_pipeline_profile(self, organization_id, profile_id):
        session = self._session_factory()
        try:
            model = session.scalar(
                select(IngestionPipelineProfile).where(
                    IngestionPipelineProfile.id == profile_id,
                    IngestionPipelineProfile.organization_id == organization_id,
                )
            )
            if model is None:
                return None
            policies = tuple(
                AdapterPolicy(
                    adapter_key=str(item["adapter_key"]),
                    enabled=bool(item.get("enabled", True)),
                    priority=(int(item["priority"]) if item.get("priority") is not None else None),
                    allowed_media_types=frozenset(str(value) for value in item.get("allowed_media_types", [])),
                )
                for item in (model.adapter_policies or [])
            )
            return IngestionPipelineProfileSnapshot(
                profile_id=model.id,
                organization_id=model.organization_id,
                revision=model.revision,
                enabled=model.enabled,
                deployment_edition=DeploymentEdition(model.deployment_edition),
                default_adapter_key=model.default_adapter_key,
                adapter_policies=policies,
                adapter_versions=dict(model.adapter_versions or {}),
                adapter_settings=dict(model.adapter_settings or {}),
            )
        finally:
            session.close()
