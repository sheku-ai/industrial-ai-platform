from __future__ import annotations

import pytest

from app.services.ingestion_adapter_resolver import (
    AdapterPolicy,
    AdapterResolutionRequest,
    DeploymentEdition,
    IngestionAdapterResolver,
)
from app.services.ingestion_contracts import AdapterCapabilities, IngestionContractError


class A:
    adapter_key = "adapter.a"
    capabilities = AdapterCapabilities(
        supported_media_types=frozenset({"text/plain"}),
        priority=20,
        community_available=True,
        enterprise_available=True,
    )


class B:
    adapter_key = "adapter.b"
    capabilities = AdapterCapabilities(
        supported_media_types=frozenset({"text/plain"}),
        priority=10,
        community_available=False,
        enterprise_available=True,
    )


class C:
    adapter_key = "adapter.c"
    capabilities = AdapterCapabilities(
        supported_media_types=frozenset({"application/pdf"}),
        priority=5,
        community_available=True,
        enterprise_available=True,
    )


def req(
    declared: str = "text/plain",
    detected: str = "text/plain",
    edition: DeploymentEdition = DeploymentEdition.COMMUNITY,
    hint: str | None = None,
) -> AdapterResolutionRequest:
    return AdapterResolutionRequest(
        declared_media_type=declared,
        detected_media_type=detected,
        deployment_edition=edition,
        adapter_hint=hint,
    )


def test_rejects_duplicate_registration() -> None:
    with pytest.raises(IngestionContractError, match="already registered"):
        IngestionAdapterResolver([A(), A()])


def test_selects_by_priority_in_enterprise() -> None:
    result = IngestionAdapterResolver([A(), B()]).resolve(
        req(edition=DeploymentEdition.ENTERPRISE), ()
    )
    assert result.adapter.adapter_key == "adapter.b"


def test_filters_by_community_edition() -> None:
    result = IngestionAdapterResolver([A(), B()]).resolve(req(), ())
    assert result.adapter.adapter_key == "adapter.a"


def test_disabled_policy_removes_adapter() -> None:
    result = IngestionAdapterResolver([A(), B()]).resolve(
        req(edition=DeploymentEdition.ENTERPRISE),
        (AdapterPolicy(adapter_key="adapter.b", enabled=False),),
    )
    assert result.adapter.adapter_key == "adapter.a"


def test_policy_priority_overrides_capability_priority() -> None:
    result = IngestionAdapterResolver([A(), B()]).resolve(
        req(edition=DeploymentEdition.ENTERPRISE),
        (AdapterPolicy(adapter_key="adapter.a", priority=1),),
    )
    assert result.adapter.adapter_key == "adapter.a"
    assert result.candidates[0].effective_priority == 1


def test_valid_hint_wins() -> None:
    result = IngestionAdapterResolver([A(), B()]).resolve(
        req(edition=DeploymentEdition.ENTERPRISE, hint="adapter.a"), ()
    )
    assert result.adapter.adapter_key == "adapter.a"
    assert result.selected_by_hint is True


def test_unsupported_hint_is_ignored() -> None:
    result = IngestionAdapterResolver([A(), C()]).resolve(req(hint="adapter.c"), ())
    assert result.adapter.adapter_key == "adapter.a"
    assert result.selected_by_hint is False


def test_policy_media_allowlist_can_exclude_adapter() -> None:
    with pytest.raises(IngestionContractError, match="no enabled ingestion adapter"):
        IngestionAdapterResolver([A()]).resolve(
            req(),
            (AdapterPolicy(adapter_key="adapter.a", allowed_media_types=frozenset({"application/pdf"})),),
        )


def test_declared_and_detected_mismatch_is_reported() -> None:
    result = IngestionAdapterResolver([A()]).resolve(
        req(declared="application/octet-stream", detected="text/plain"), ()
    )
    assert result.declared_media_type_matches is False


def test_rejects_duplicate_policies() -> None:
    with pytest.raises(IngestionContractError, match="duplicate adapter policy"):
        IngestionAdapterResolver([A()]).resolve(
            req(),
            (AdapterPolicy(adapter_key="adapter.a"), AdapterPolicy(adapter_key="adapter.a")),
        )


def test_registered_keys_are_stable() -> None:
    resolver = IngestionAdapterResolver([C(), A(), B()])
    assert resolver.registered_adapter_keys() == ("adapter.a", "adapter.b", "adapter.c")
