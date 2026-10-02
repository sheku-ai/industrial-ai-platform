from __future__ import annotations

from uuid import uuid4

from app.services.runtime_worker import (
    RuntimeAdapterRegistry,
    RuntimeAdapterResult,
    RuntimeWorkItem,
)


class SuccessfulAdapter:
    execution_type = "generic.success"

    def execute(self, item, heartbeat):
        heartbeat.pulse()
        return RuntimeAdapterResult(metrics={"processed": 1})


def test_registry_rejects_duplicate_execution_type() -> None:
    registry = RuntimeAdapterRegistry()
    registry.register(SuccessfulAdapter())

    try:
        registry.register(SuccessfulAdapter())
    except ValueError as exc:
        assert "already registered" in str(exc)
    else:
        raise AssertionError("duplicate adapter registration was accepted")


def test_registry_resolves_configured_adapter() -> None:
    registry = RuntimeAdapterRegistry()
    adapter = SuccessfulAdapter()
    registry.register(adapter)

    assert registry.resolve(adapter.execution_type) is adapter


def test_registry_returns_none_for_unconfigured_execution_type() -> None:
    assert RuntimeAdapterRegistry().resolve("unconfigured.type") is None


def test_adapter_result_defaults_to_terminal_execution() -> None:
    result = RuntimeAdapterResult(metrics={"processed": 1})

    assert result.metrics == {"processed": 1}
    assert result.continue_execution is False


def test_adapter_result_can_request_durable_continuation() -> None:
    result = RuntimeAdapterResult(continue_execution=True)

    assert result.continue_execution is True


def test_work_item_preserves_runtime_identity_and_payload() -> None:
    organization_id = uuid4()
    execution_id = uuid4()
    lease_token = uuid4()
    item = RuntimeWorkItem(
        organization_id=organization_id,
        execution_id=execution_id,
        execution_type="generic.success",
        subject_type="generic.subject",
        subject_id=uuid4(),
        attempt_id=uuid4(),
        attempt_number=1,
        lease_token=lease_token,
        input_payload={"value": 1},
        policy_snapshot={"policy": "configured"},
    )

    assert item.organization_id == organization_id
    assert item.execution_id == execution_id
    assert item.lease_token == lease_token
    assert item.input_payload == {"value": 1}
