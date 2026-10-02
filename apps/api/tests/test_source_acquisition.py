from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest

from app.services.ingestion_contracts import IngestionContractError
from app.services.source_acquisition import SourceObjectDescriptor, WorkspaceSourceAcquisitionService


class Reader:
    def __init__(self, payload: bytes, *, file_name: str = "input.txt") -> None:
        self.payload = payload
        self.reference = "object://source/input"
        self.file_name = file_name
        self.described = 0
        self.opened = 0

    def describe(self, organization_id, source_reference):
        del organization_id
        self.described += 1
        assert source_reference == self.reference
        return SourceObjectDescriptor(
            source_reference=self.reference,
            media_type="text/plain",
            content_length=len(self.payload),
            checksum_sha256=sha256(self.payload).hexdigest(),
            file_name=self.file_name,
        )

    def open_stream(self, organization_id, source_reference):
        del organization_id
        self.opened += 1
        assert source_reference == self.reference
        return BytesIO(self.payload)


def test_acquires_source_into_isolated_workspace(tmp_path: Path) -> None:
    reader = Reader(b"content")
    organization_id = uuid4()
    execution_id = uuid4()
    service = WorkspaceSourceAcquisitionService(reader, tmp_path)

    result = service.acquire(
        organization_id,
        reader.reference,
        execution_id=execution_id,
        attempt_number=2,
    )

    target = Path(result.local_path)
    assert target.read_bytes() == b"content"
    assert target.parent == (
        tmp_path.resolve() / str(organization_id) / str(execution_id) / "2"
    )
    assert result.checksum_sha256 == sha256(b"content").hexdigest()
    assert reader.described == 1
    assert reader.opened == 1


def test_sanitizes_untrusted_file_name(tmp_path: Path) -> None:
    reader = Reader(b"content", file_name="../../unsafe name?.txt")
    result = WorkspaceSourceAcquisitionService(reader, tmp_path).acquire(
        uuid4(), reader.reference, execution_id=uuid4(), attempt_number=1
    )
    assert Path(result.local_path).name == "unsafe_name_.txt"


def test_rejects_descriptor_over_size_limit(tmp_path: Path) -> None:
    reader = Reader(b"12345")
    service = WorkspaceSourceAcquisitionService(reader, tmp_path, max_source_bytes=4)
    with pytest.raises(IngestionContractError, match="acquisition limit"):
        service.acquire(uuid4(), reader.reference, execution_id=uuid4(), attempt_number=1)
    assert reader.opened == 0


def test_rejects_checksum_mismatch_and_removes_partial(tmp_path: Path) -> None:
    reader = Reader(b"content")
    original_describe = reader.describe

    def bad_describe(organization_id, source_reference):
        descriptor = original_describe(organization_id, source_reference)
        return SourceObjectDescriptor(
            source_reference=descriptor.source_reference,
            media_type=descriptor.media_type,
            content_length=descriptor.content_length,
            checksum_sha256="0" * 64,
            file_name=descriptor.file_name,
        )

    reader.describe = bad_describe
    service = WorkspaceSourceAcquisitionService(reader, tmp_path)
    with pytest.raises(IngestionContractError, match="checksum"):
        service.acquire(uuid4(), reader.reference, execution_id=uuid4(), attempt_number=1)
    assert not list(tmp_path.rglob("*.partial"))


def test_rejects_non_hex_descriptor_checksum(tmp_path: Path) -> None:
    reader = Reader(b"content")
    original_describe = reader.describe

    def bad_describe(organization_id, source_reference):
        descriptor = original_describe(organization_id, source_reference)
        return SourceObjectDescriptor(
            source_reference=descriptor.source_reference,
            media_type=descriptor.media_type,
            content_length=descriptor.content_length,
            checksum_sha256="z" * 64,
            file_name=descriptor.file_name,
        )

    reader.describe = bad_describe
    with pytest.raises(IngestionContractError, match="lowercase SHA-256"):
        WorkspaceSourceAcquisitionService(reader, tmp_path).acquire(
            uuid4(), reader.reference, execution_id=uuid4(), attempt_number=1
        )
    assert reader.opened == 0


def test_rejects_invalid_attempt_number(tmp_path: Path) -> None:
    reader = Reader(b"content")
    with pytest.raises(IngestionContractError, match="attempt_number"):
        WorkspaceSourceAcquisitionService(reader, tmp_path).acquire(
            uuid4(), reader.reference, execution_id=uuid4(), attempt_number=0
        )


def test_service_has_no_provider_specific_state(tmp_path: Path) -> None:
    service = WorkspaceSourceAcquisitionService(Reader(b"content"), tmp_path)
    assert not hasattr(service, "minio")
    assert not hasattr(service, "s3")
    assert not hasattr(service, "session")
