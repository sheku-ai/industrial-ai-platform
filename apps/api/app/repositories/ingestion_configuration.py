from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ingestion import IngestionPipelineProfile
from app.services.ingestion_adapter_resolver import AdapterPolicy, DeploymentEdition
from app.services.ingestion_configuration import IngestionPipelineProfileSnapshot
from app.services.ingestion_contracts import IngestionContractError


class SqlAlchemyIngestionConfigurationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_pipeline_profile(self, organization_id, profile_id):
        row = self._session.scalar(
            select(IngestionPipelineProfile).where(
                IngestionPipelineProfile.id == profile_id,
                IngestionPipelineProfile.organization_id == organization_id,
            )
        )
        if row is None:
            return None

        try:
            edition = DeploymentEdition(row.deployment_edition)
            policies = tuple(_policy(item) for item in row.adapter_policies)
            versions = dict(row.adapter_versions)
            settings = {key: dict(value) for key, value in row.adapter_settings.items()}
        except (TypeError, ValueError, KeyError) as exc:
            raise IngestionContractError("stored ingestion pipeline profile is invalid") from exc

        return IngestionPipelineProfileSnapshot(
            profile_id=row.id,
            organization_id=row.organization_id,
            revision=row.revision,
            enabled=row.enabled,
            deployment_edition=edition,
            default_adapter_key=row.default_adapter_key,
            adapter_policies=policies,
            adapter_versions=versions,
            adapter_settings=settings,
        )


def _policy(value):
    if not isinstance(value, dict):
        raise IngestionContractError("adapter policy must be an object")
    allowed_media_types = value.get("allowed_media_types", ())
    if not isinstance(allowed_media_types, list | tuple | set | frozenset):
        raise IngestionContractError("allowed_media_types must be an array")
    return AdapterPolicy(
        adapter_key=value["adapter_key"],
        enabled=value.get("enabled", True),
        priority=value.get("priority"),
        allowed_media_types=frozenset(allowed_media_types),
    )
