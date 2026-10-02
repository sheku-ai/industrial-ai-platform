from __future__ import annotations

import uuid

import pytest
from sqlalchemy import inspect

from app.models.core import Organization
from app.models.organization_lifecycle import OrganizationDeletionExecution
from app.schemas.core import OrganizationDeletionRequest
from app.services import organization_deletion
from app.services.organization_deletion import (
    _delete_filesystem_object,
    _inventory_external_objects,
    _request_hash,
    _validate_deletable,
    delete_organization_governed,
    preview_organization_deletion,
)


def _organization(config: dict) -> Organization:
    return Organization(slug="validation", name="Validation", status="active", config=config)


def test_deletion_execution_retains_identity_without_organization_foreign_key() -> None:
    mapper = inspect(OrganizationDeletionExecution)

    assert mapper.local_table.schema == "core"
    assert mapper.local_table.name == "organization_deletion_executions"
    assert not mapper.local_table.c.organization_id.foreign_keys


def test_validation_organization_requires_explicit_deletion_metadata() -> None:
    assert _validate_deletable(_organization({"organization_class": "validation"})) == [
        {"code": "deletion_not_allowed", "message": "Organization deletion is not enabled."}
    ]
    assert not _validate_deletable(
        _organization(
            {
                "organization_class": "validation",
                "environment_purpose": "product_validation",
                "deletion_allowed": True,
            }
        )
    )


def test_protected_organization_remains_blocked_even_when_deletion_is_enabled() -> None:
    blockers = _validate_deletable(
        _organization({"deletion_allowed": True, "reference_tenant": True, "canonical_product_reference": True})
    )

    assert [item["code"] for item in blockers] == ["protected_organization"]
    assert blockers[0]["markers"] == ["reference_tenant", "canonical_product_reference"]


def test_deletion_request_hash_is_stable_and_actor_bound() -> None:
    organization_id = uuid.uuid4()

    assert _request_hash(organization_id, "actor-a") == _request_hash(organization_id, "actor-a")
    assert _request_hash(organization_id, "actor-a") != _request_hash(organization_id, "actor-b")


def test_filesystem_deletion_removes_binary_and_metadata_sidecar(tmp_path) -> None:
    binary = tmp_path / "object-key"
    sidecar = tmp_path / "object-key.metadata.json"
    binary.write_bytes(b"content")
    sidecar.write_text('{"checksum":"sha256:test"}', encoding="utf-8")

    _delete_filesystem_object(str(tmp_path), binary.name)

    assert not binary.exists()
    assert not sidecar.exists()


def _filesystem_object(tmp_path, object_key: str = "object-key") -> dict:
    binary = tmp_path / object_key
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"content")
    binary.with_name(f"{binary.name}.metadata.json").write_text("{}", encoding="utf-8")
    return {
        "provider": "filesystem",
        "bucket": str(tmp_path),
        "object_key": object_key,
        "origin": "documents.artifacts",
    }


def test_filesystem_inventory_does_not_require_unrelated_minio(tmp_path, monkeypatch) -> None:
    item = _filesystem_object(tmp_path)
    monkeypatch.setattr(
        organization_deletion,
        "_s3_client",
        lambda: pytest.fail("S3 client must not be created for filesystem-only inventory"),
    )

    objects, warnings, blockers = _inventory_external_objects([item], uuid.uuid4())

    assert objects == [item]
    assert warnings == []
    assert blockers == []


def test_filesystem_binary_missing_blocks_preview_inventory(tmp_path) -> None:
    item = _filesystem_object(tmp_path)
    (tmp_path / item["object_key"]).unlink()

    _, _, blockers = _inventory_external_objects([item], uuid.uuid4())

    assert [blocker["code"] for blocker in blockers] == ["filesystem_object_binary_missing"]


def test_filesystem_sidecar_missing_blocks_preview_inventory(tmp_path) -> None:
    item = _filesystem_object(tmp_path)
    (tmp_path / f'{item["object_key"]}.metadata.json').unlink()

    _, _, blockers = _inventory_external_objects([item], uuid.uuid4())

    assert [blocker["code"] for blocker in blockers] == ["filesystem_object_metadata_missing"]


class AvailableRemoteInventory:
    def __init__(self) -> None:
        self.head_calls: list[tuple[str, str]] = []
        self.list_calls: list[tuple[str, str]] = []

    def head_object(self, *, Bucket: str, Key: str) -> dict:
        self.head_calls.append((Bucket, Key))
        return {}

    def list_objects_v2(self, *, Bucket: str, Prefix: str, **kwargs) -> dict:
        del kwargs
        self.list_calls.append((Bucket, Prefix))
        return {"Contents": [], "IsTruncated": False}


def test_filesystem_and_s3_inventory_are_evaluated_independently(tmp_path, monkeypatch) -> None:
    organization_id = uuid.uuid4()
    filesystem_item = _filesystem_object(tmp_path)
    s3_item = {
        "provider": "s3",
        "bucket": "required-bucket",
        "object_key": "persisted/object-key",
        "origin": "documents.artifacts",
    }
    client = AvailableRemoteInventory()
    monkeypatch.setattr(organization_deletion, "_s3_client", lambda: client)

    objects, warnings, blockers = _inventory_external_objects(
        [filesystem_item, s3_item],
        organization_id,
    )

    assert len(objects) == 2
    assert warnings == []
    assert blockers == []
    assert client.head_calls == [("required-bucket", "persisted/object-key")]
    assert client.list_calls == [("required-bucket", f"{organization_id}/")]


def test_required_s3_unavailable_blocks_preview_inventory(monkeypatch) -> None:
    item = {
        "provider": "s3",
        "bucket": "required-bucket",
        "object_key": "persisted/object-key",
        "origin": "documents.artifacts",
    }
    monkeypatch.setattr(
        organization_deletion,
        "_s3_client",
        lambda: (_ for _ in ()).throw(ConnectionError("unavailable")),
    )

    _, warnings, blockers = _inventory_external_objects([item], uuid.uuid4())

    assert [warning["code"] for warning in warnings] == ["object_storage_preview_unavailable"]
    assert [blocker["code"] for blocker in blockers] == ["object_storage_inventory_unavailable"]
    assert blockers[0]["provider"] == "s3"
    assert blockers[0]["bucket"] == "required-bucket"


def test_unknown_provider_blocks_preview_inventory(monkeypatch) -> None:
    item = {
        "provider": "unknown-provider",
        "bucket": "unknown-root",
        "object_key": "object-key",
        "origin": "documents.artifacts",
    }
    monkeypatch.setattr(
        organization_deletion,
        "_s3_client",
        lambda: pytest.fail("S3 client must not be created for an unknown provider"),
    )

    _, warnings, blockers = _inventory_external_objects([item], uuid.uuid4())

    assert warnings == []
    assert [blocker["code"] for blocker in blockers] == ["unsupported_object_storage_provider"]


def _execution(*, organization_id: uuid.UUID, actor: str, key: str, status: str) -> OrganizationDeletionExecution:
    return OrganizationDeletionExecution(
        id=uuid.uuid4(),
        organization_id=organization_id,
        idempotency_key=key,
        request_hash=_request_hash(organization_id, actor),
        organization_name_hash="0" * 64,
        requested_by=actor,
        status=status,
        resource_counts_before={},
        resource_counts_deleted={},
        external_objects=[],
        object_storage_objects_deleted=0,
        blockers=[],
        warnings=[],
        correlation_id="correlation-id",
    )


def test_preview_replay_is_idempotent(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    actor = "actor"
    key = "preview-key"
    execution = _execution(
        organization_id=organization_id,
        actor=actor,
        key=key,
        status="deletion_previewed",
    )
    organization = _organization({"deletion_allowed": True})
    organization.id = organization_id
    monkeypatch.setattr(organization_deletion, "_find_execution", lambda *args, **kwargs: execution)

    result = preview_organization_deletion(
        None,
        organization,
        OrganizationDeletionRequest(idempotency_key=key),
        requested_by=actor,
        correlation_id="new-correlation-id",
    )

    assert result.deletion_execution_id == execution.id
    assert result.replayed is True


def test_delete_replay_is_idempotent(monkeypatch) -> None:
    organization_id = uuid.uuid4()
    actor = "actor"
    key = "delete-key"
    execution = _execution(
        organization_id=organization_id,
        actor=actor,
        key=key,
        status="deleted",
    )
    monkeypatch.setattr(organization_deletion, "_find_execution", lambda *args, **kwargs: execution)

    result = delete_organization_governed(
        None,
        organization_id,
        OrganizationDeletionRequest(idempotency_key=key),
        requested_by=actor,
        correlation_id="new-correlation-id",
    )

    assert result.deletion_execution_id == execution.id
    assert result.replayed is True
