from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.services.runtime_compatibility import (
    DomainJobNotFoundError,
    DomainTenantMismatchError,
    RuntimeCompatibilityService,
)


class _MappingResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def one_or_none(self):
        return self._row


def _service(row):
    session = MagicMock()
    session.execute.return_value = _MappingResult(row)
    service = RuntimeCompatibilityService(session)
    service.lifecycle = MagicMock()
    return service, session


def test_disabled_compatibility_returns_without_touching_database() -> None:
    session = MagicMock()
    service = RuntimeCompatibilityService(session, enabled=False)

    assert service.link_ingestion_job(uuid4()) is None
    session.execute.assert_not_called()


def test_missing_domain_job_is_rejected() -> None:
    service, _ = _service(None)

    with pytest.raises(DomainJobNotFoundError):
        service.link_ingestion_job(uuid4())


def test_ingestion_job_creates_provider_neutral_runtime_link() -> None:
    job_id = uuid4()
    organization_id = uuid4()
    execution_id = uuid4()
    service, session = _service(
        {
            "id": job_id,
            "organization_id": organization_id,
            "document_version_id": uuid4(),
            "requested_by": "user-1",
            "job_type": "extract",
            "priority": 50,
            "runtime_execution_id": None,
        }
    )
    service.lifecycle.create_or_get.return_value = (SimpleNamespace(id=execution_id), True)

    link = service.link_ingestion_job(job_id)

    assert link.domain_kind == "document.ingestion"
    assert link.runtime_execution_id == execution_id
    assert link.created is True
    kwargs = service.lifecycle.create_or_get.call_args.kwargs
    assert kwargs["organization_id"] == organization_id
    assert kwargs["execution_type"] == "document.ingestion"
    assert kwargs["subject_type"] == "documents.ingestion_job"
    assert kwargs["idempotency_key"] == f"document.ingestion:{job_id}"
    assert "status" not in kwargs["input_payload"]
    assert session.execute.call_count == 2
    session.commit.assert_not_called()
    session.rollback.assert_not_called()


def test_existing_link_is_reused_without_creating_execution() -> None:
    job_id = uuid4()
    organization_id = uuid4()
    execution_id = uuid4()
    service, _ = _service(
        {
            "id": job_id,
            "organization_id": organization_id,
            "document_version_id": None,
            "index_target": "lexical",
            "runtime_execution_id": execution_id,
        }
    )
    service.lifecycle.executions.get.return_value = SimpleNamespace(id=execution_id)

    link = service.link_indexing_job(job_id)

    assert link.runtime_execution_id == execution_id
    assert link.created is False
    service.lifecycle.create_or_get.assert_not_called()


def test_connector_run_resolves_tenant_from_connector() -> None:
    run_id = uuid4()
    organization_id = uuid4()
    execution_id = uuid4()
    service, _ = _service(
        {
            "id": run_id,
            "runtime_execution_id": None,
            "organization_id": organization_id,
            "connector_id": uuid4(),
        }
    )
    service.lifecycle.create_or_get.return_value = (SimpleNamespace(id=execution_id), True)

    link = service.link_connector_run(run_id)

    assert link.organization_id == organization_id
    kwargs = service.lifecycle.create_or_get.call_args.kwargs
    assert kwargs["execution_type"] == "connector.run"
    assert kwargs["subject_type"] == "connectors.connector_run"


def test_global_connector_run_is_rejected() -> None:
    service, _ = _service(
        {
            "id": uuid4(),
            "runtime_execution_id": None,
            "organization_id": None,
            "connector_id": uuid4(),
        }
    )

    with pytest.raises(DomainTenantMismatchError):
        service.link_connector_run(uuid4())
