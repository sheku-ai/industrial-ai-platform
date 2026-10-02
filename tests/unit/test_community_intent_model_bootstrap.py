from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.services import community_intent_model_bootstrap as bootstrap


def _manifest(*, artifact_hash: str = "a" * 64) -> dict[str, object]:
    return {
        "model_family": "conversation_intent",
        "provider": "community.setfit",
        "model_version": "community-intent-v1",
        "dataset_version": "community-intent-dataset-v1",
        "base_model": "intfloat/multilingual-e5-small",
        "artifact_reference": "runtime/intent-models/community-intent-v1",
        "artifact_hash": artifact_hash,
        "dataset_hash": "d" * 64,
        "build_configuration_hash": "c" * 64,
        "intent_catalog": [
            "knowledge_query",
            "contextual_follow_up",
            "new_topic",
            "response_refinement",
            "citation_request",
            "conversation_summary",
            "non_knowledge_interaction",
        ],
        "languages": ["es", "en"],
        "offline_runtime": True,
    }


def _record(**overrides):
    values = {
        "organization_id": None,
        "organization_node_id": None,
        "ownership_scope": "global",
        "scope_type": "community",
        "data_origin": "operational",
        "model_family": "conversation_intent",
        "provider": "community.setfit",
        "model_version": "community-intent-v1",
        "model_status": "active",
        "artifact_reference": "runtime/intent-models/community-intent-v1",
        "artifact_hash": "a" * 64,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _Session:
    def begin_nested(self):
        return nullcontext()


def _install_artifact_boundary(monkeypatch) -> dict[str, object]:
    manifest = _manifest()
    monkeypatch.setattr(
        bootstrap,
        "load_and_validate_artifact_manifest",
        lambda path: manifest,
    )
    monkeypatch.setattr(bootstrap, "verify_setfit_artifact", lambda path: None)
    monkeypatch.setattr(bootstrap, "artifact_hash", lambda path: manifest["artifact_hash"])
    return manifest


def test_bootstrap_registers_packaged_community_model(monkeypatch, tmp_path) -> None:
    manifest = _install_artifact_boundary(monkeypatch)
    created = _record()
    captured: dict[str, object] = {}

    class Repository:
        def __init__(self, session):
            assert isinstance(session, _Session)

        def get_community_models_by_version(self, **kwargs):
            captured["version_query"] = kwargs
            return []

        def get_active_community_model(self, model_family):
            captured["active_query"] = model_family
            return None

        def create_community_model(self, **kwargs):
            captured["create"] = kwargs
            return created

    monkeypatch.setattr(bootstrap, "ConversationIntentModelRepository", Repository)

    result = bootstrap.bootstrap_community_intent_model(
        _Session(),
        artifact_directory=tmp_path,
    )

    assert result.model is created
    assert result.reused is False
    assert captured["version_query"] == {
        "model_family": "conversation_intent",
        "model_version": "community-intent-v1",
    }
    assert captured["active_query"] == "conversation_intent"
    assert captured["create"] == {
        "model_family": "conversation_intent",
        "provider": "community.setfit",
        "model_version": "community-intent-v1",
        "artifact_reference": "runtime/intent-models/community-intent-v1",
        "artifact_hash": "a" * 64,
        "model_metadata": {
            "dataset_version": "community-intent-dataset-v1",
            "dataset_hash": "d" * 64,
            "base_model": "intfloat/multilingual-e5-small",
            "build_configuration_hash": "c" * 64,
            "intent_catalog": manifest["intent_catalog"],
            "languages": ["es", "en"],
            "offline_runtime": True,
        },
    }


def test_bootstrap_reuses_exact_active_version_without_duplicate(monkeypatch, tmp_path) -> None:
    _install_artifact_boundary(monkeypatch)
    existing = _record()

    class Repository:
        def __init__(self, session):
            pass

        def get_community_models_by_version(self, **kwargs):
            return [existing]

        def create_community_model(self, **kwargs):
            raise AssertionError("idempotent bootstrap must not create a duplicate")

    monkeypatch.setattr(bootstrap, "ConversationIntentModelRepository", Repository)

    result = bootstrap.bootstrap_community_intent_model(
        _Session(),
        artifact_directory=tmp_path,
    )

    assert result.model is existing
    assert result.reused is True


def test_bootstrap_does_not_replace_different_active_model(monkeypatch, tmp_path) -> None:
    _install_artifact_boundary(monkeypatch)
    different = _record(
        model_version="community-intent-v0",
        artifact_hash="0" * 64,
    )

    class Repository:
        def __init__(self, session):
            pass

        def get_community_models_by_version(self, **kwargs):
            return []

        def get_active_community_model(self, model_family):
            return different

        def create_community_model(self, **kwargs):
            raise AssertionError("bootstrap must not replace PostgreSQL authority")

    monkeypatch.setattr(bootstrap, "ConversationIntentModelRepository", Repository)

    with pytest.raises(
        bootstrap.CommunityIntentModelBootstrapConflict,
        match="automatic replacement is disabled",
    ):
        bootstrap.bootstrap_community_intent_model(
            _Session(),
            artifact_directory=tmp_path,
        )


def test_bootstrap_rejects_same_version_with_different_artifact(monkeypatch, tmp_path) -> None:
    _install_artifact_boundary(monkeypatch)
    conflicting = _record(artifact_hash="f" * 64)

    class Repository:
        def __init__(self, session):
            pass

        def get_community_models_by_version(self, **kwargs):
            return [conflicting]

    monkeypatch.setattr(bootstrap, "ConversationIntentModelRepository", Repository)

    with pytest.raises(
        bootstrap.CommunityIntentModelBootstrapConflict,
        match="artifact_hash",
    ):
        bootstrap.bootstrap_community_intent_model(
            _Session(),
            artifact_directory=tmp_path,
        )


def _integrity_error(constraint_name: str) -> IntegrityError:
    original = RuntimeError("unique violation")
    original.diag = SimpleNamespace(constraint_name=constraint_name)
    return IntegrityError("insert", {}, original)


def test_concurrent_bootstrap_reuses_expected_unique_winner(monkeypatch, tmp_path) -> None:
    _install_artifact_boundary(monkeypatch)
    winner = _record()
    active_results = iter((None, winner))

    class Repository:
        def __init__(self, session):
            pass

        def get_community_models_by_version(self, **kwargs):
            return []

        def get_active_community_model(self, model_family):
            return next(active_results)

        def create_community_model(self, **kwargs):
            raise _integrity_error(bootstrap.COMMUNITY_ACTIVE_MODEL_CONSTRAINT)

    monkeypatch.setattr(bootstrap, "ConversationIntentModelRepository", Repository)

    result = bootstrap.bootstrap_community_intent_model(
        _Session(),
        artifact_directory=tmp_path,
    )

    assert result.model is winner
    assert result.reused is True


def test_bootstrap_propagates_unrelated_integrity_error(monkeypatch, tmp_path) -> None:
    _install_artifact_boundary(monkeypatch)

    class Repository:
        def __init__(self, session):
            pass

        def get_community_models_by_version(self, **kwargs):
            return []

        def get_active_community_model(self, model_family):
            return None

        def create_community_model(self, **kwargs):
            raise _integrity_error("unrelated_constraint")

    monkeypatch.setattr(bootstrap, "ConversationIntentModelRepository", Repository)

    with pytest.raises(IntegrityError):
        bootstrap.bootstrap_community_intent_model(
            _Session(),
            artifact_directory=tmp_path,
        )
