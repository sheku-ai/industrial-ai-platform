
import pytest

from app.repositories.ingestion_configuration import _policy
from app.services.ingestion_contracts import IngestionContractError


def test_maps_stored_adapter_policy():
    policy = _policy(
        {
            "adapter_key": "platform.text.plain",
            "enabled": True,
            "priority": 10,
            "allowed_media_types": ["text/plain", "text/markdown"],
        }
    )
    assert policy.adapter_key == "platform.text.plain"
    assert policy.priority == 10
    assert policy.allowed_media_types == frozenset({"text/plain", "text/markdown"})


def test_rejects_invalid_allowed_media_types():
    with pytest.raises(IngestionContractError, match="must be an array"):
        _policy(
            {
                "adapter_key": "platform.text.plain",
                "allowed_media_types": "text/plain",
            }
        )


def test_profile_model_uses_documents_schema():
    from app.models.ingestion import IngestionPipelineProfile

    assert IngestionPipelineProfile.__table__.schema == "documents"
    assert IngestionPipelineProfile.__tablename__ == "ingestion_pipeline_profiles"
