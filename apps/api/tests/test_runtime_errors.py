from __future__ import annotations

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.api.runtime_errors import runtime_http_error


def test_runtime_error_maps_public_failure_contracts() -> None:
    assert runtime_http_error(ValueError("invalid_scope")).status_code == 400
    assert runtime_http_error(LookupError("capacity_profile_not_found")).status_code == 404
    assert runtime_http_error(ValueError("idempotency_key_conflict")).status_code == 409
    assert runtime_http_error(IntegrityError("insert", {}, Exception("unique"))).status_code == 409


def test_runtime_error_never_exposes_internal_exception_details() -> None:
    internal = runtime_http_error(RuntimeError("postgresql://secret@internal/runtime"))
    persistence = runtime_http_error(SQLAlchemyError("credential-bearing database failure"))

    assert internal.status_code == 500
    assert internal.detail == "runtime_operation_failed"
    assert persistence.status_code == 500
    assert persistence.detail == "runtime_persistence_error"
