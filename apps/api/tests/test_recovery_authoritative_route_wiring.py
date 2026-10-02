from __future__ import annotations

from app.api.routes import recovery as recovery_routes
from app.api.routes import recovery_authoritative
from app.services import (
    production_acceptance_runtime,
    recovery_authoritative_completion,
    recovery_authoritative_verification,
)
from app.services import recovery_objectives_runtime as objectives_runtime


def test_existing_recovery_completion_routes_use_authoritative_runtime() -> None:
    assert recovery_routes.complete_backup_execution is recovery_authoritative_completion.complete_backup_execution
    assert recovery_routes.complete_restore_execution is recovery_authoritative_completion.complete_restore_execution
    assert (
        recovery_routes.complete_restore_verification
        is recovery_authoritative_verification.complete_restore_verification
    )


def test_recovery_consumers_import_authoritative_readiness_directly() -> None:
    assert recovery_routes.build_recovery_readiness is objectives_runtime.build_recovery_readiness
    assert recovery_routes.build_recovery_workspace_runtime is objectives_runtime.build_recovery_workspace_runtime
    assert production_acceptance_runtime.build_recovery_readiness is objectives_runtime.build_recovery_readiness


def test_recovery_evidence_router_has_no_runtime_wiring_side_effects() -> None:
    assert not hasattr(recovery_authoritative, "recovery_routes")
    assert not hasattr(recovery_authoritative, "recovery_runtime")
    assert not hasattr(recovery_authoritative, "production_acceptance_runtime")


def test_authoritative_recovery_evidence_routes_are_registered() -> None:
    paths = {route.path for route in recovery_authoritative.router.routes}
    assert "/platform/recovery/provider-execution-evidence" in paths
    assert "/platform/recovery/verifications/{verification_id}/check-evidence" in paths
