from __future__ import annotations

import uuid

import pytest

import app.services.enterprise_search_configuration as configuration


def test_enterprise_search_configuration_uses_product_fallback(monkeypatch) -> None:
    monkeypatch.setattr(configuration, "_load_active_payload", lambda *_args, **_kwargs: None)

    resolved = configuration.resolve_enterprise_search_configuration(
        object(),
        organization_id=uuid.uuid4(),
        requested_limit=None,
        requested_top_k=None,
    )

    assert resolved.source == "product_fallback"
    assert resolved.effective_limit == 10
    assert resolved.max_limit == 50
    assert resolved.effective_top_k == 10
    assert resolved.max_top_k == 100


def test_enterprise_search_configuration_prefers_organization_override(monkeypatch) -> None:
    organization_id = uuid.uuid4()

    def _payload(_db, *, organization_id: uuid.UUID | None):
        if organization_id is None:
            return {"default_limit": 20, "max_limit": 40, "default_top_k": 15, "max_top_k": 80}
        return {"default_limit": 25, "max_limit": 30}

    monkeypatch.setattr(configuration, "_load_active_payload", _payload)

    resolved = configuration.resolve_enterprise_search_configuration(
        object(),
        organization_id=organization_id,
        requested_limit=None,
        requested_top_k=None,
    )

    assert resolved.source == "organization"
    assert resolved.effective_limit == 25
    assert resolved.max_limit == 30
    assert resolved.effective_top_k == 15
    assert resolved.max_top_k == 80


def test_enterprise_search_configuration_preserves_explicit_request(monkeypatch) -> None:
    monkeypatch.setattr(configuration, "_load_active_payload", lambda *_args, **_kwargs: None)

    resolved = configuration.resolve_enterprise_search_configuration(
        object(),
        organization_id=uuid.uuid4(),
        requested_limit=20,
        requested_top_k=30,
    )

    assert resolved.effective_limit == 20
    assert resolved.effective_top_k == 30


def test_enterprise_search_configuration_rejects_request_over_configured_max(monkeypatch) -> None:
    def _payload(_db, *, organization_id: uuid.UUID | None):
        if organization_id is None:
            return {"max_limit": 15}
        return None

    monkeypatch.setattr(configuration, "_load_active_payload", _payload)

    with pytest.raises(ValueError, match="limit exceeds configured maximum of 15"):
        configuration.resolve_enterprise_search_configuration(
            object(),
            organization_id=uuid.uuid4(),
            requested_limit=20,
            requested_top_k=None,
        )
