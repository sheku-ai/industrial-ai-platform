from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.ingestion_adapter_resolver import AdapterPolicy, DeploymentEdition
from app.services.ingestion_configuration import IngestionConfigurationService, IngestionPipelineProfileSnapshot
from app.services.ingestion_contracts import IngestionContractError


class Repository:
    def __init__(self, profile: IngestionPipelineProfileSnapshot | None) -> None:
        self.profile = profile

    def get_pipeline_profile(self, organization_id, profile_id):
        del organization_id, profile_id
        return self.profile


def profile(*, enabled: bool = True, default: str | None = "platform.text.plain"):
    organization_id = uuid4()
    return IngestionPipelineProfileSnapshot(
        profile_id=uuid4(),
        organization_id=organization_id,
        revision="rev-1",
        enabled=enabled,
        deployment_edition=DeploymentEdition.COMMUNITY,
        default_adapter_key=default,
        adapter_policies=(
            AdapterPolicy(adapter_key="platform.text.plain", enabled=True),
            AdapterPolicy(adapter_key="platform.pdf.text_layer", enabled=True),
        ),
        adapter_versions={
            "platform.text.plain": "1.0.0",
            "platform.pdf.text_layer": "1.0.0",
        },
        adapter_settings={
            "platform.text.plain": {"split_on_blank_lines": False},
        },
    )


def test_resolves_default_adapter_configuration() -> None:
    snapshot = profile()
    resolved = IngestionConfigurationService(Repository(snapshot)).resolve(
        snapshot.organization_id,
        snapshot.profile_id,
    )
    assert resolved.adapter_configuration.adapter_key == "platform.text.plain"
    assert resolved.adapter_configuration.adapter_version == "1.0.0"
    assert resolved.adapter_configuration.pipeline_profile_revision == "rev-1"
    assert resolved.adapter_configuration.settings["split_on_blank_lines"] is False


def test_resolves_requested_enabled_adapter() -> None:
    snapshot = profile()
    resolved = IngestionConfigurationService(Repository(snapshot)).resolve(
        snapshot.organization_id,
        snapshot.profile_id,
        requested_adapter_key="platform.pdf.text_layer",
    )
    assert resolved.adapter_configuration.adapter_key == "platform.pdf.text_layer"


def test_rejects_missing_profile() -> None:
    with pytest.raises(IngestionContractError, match="was not found"):
        IngestionConfigurationService(Repository(None)).resolve(uuid4(), uuid4())


def test_rejects_disabled_profile() -> None:
    snapshot = profile(enabled=False)
    with pytest.raises(IngestionContractError, match="disabled"):
        IngestionConfigurationService(Repository(snapshot)).resolve(
            snapshot.organization_id,
            snapshot.profile_id,
        )


def test_rejects_unconfigured_adapter_version() -> None:
    snapshot = profile()
    broken = IngestionPipelineProfileSnapshot(
        profile_id=snapshot.profile_id,
        organization_id=snapshot.organization_id,
        revision=snapshot.revision,
        enabled=True,
        deployment_edition=snapshot.deployment_edition,
        default_adapter_key=snapshot.default_adapter_key,
        adapter_policies=snapshot.adapter_policies,
        adapter_versions={"platform.pdf.text_layer": "1.0.0"},
        adapter_settings=snapshot.adapter_settings,
    )
    with pytest.raises(IngestionContractError, match="version is not configured"):
        IngestionConfigurationService(Repository(broken)).resolve(
            broken.organization_id,
            broken.profile_id,
        )


def test_rejects_ambiguous_profile_without_default() -> None:
    snapshot = profile(default=None)
    with pytest.raises(IngestionContractError, match="unique adapter"):
        IngestionConfigurationService(Repository(snapshot)).resolve(
            snapshot.organization_id,
            snapshot.profile_id,
        )
