from typing import Any

from fastapi import APIRouter

from app.services.platform_diagnostics import (
    build_platform_diagnostics,
    build_platform_diagnostics_catalog,
    build_platform_diagnostics_issues,
    build_platform_diagnostics_remediation,
    build_platform_diagnostics_summary,
)
from app.services.platform_journey import build_platform_journey
from app.services.platform_journey_acceptance import build_platform_journey_acceptance
from app.services.platform_journey_bundle import build_platform_journey_bundle
from app.services.platform_journey_closeout import build_platform_journey_closeout_package
from app.services.platform_journey_closeout_checklist import build_platform_journey_closeout_checklist
from app.services.platform_journey_completion_report import build_platform_journey_completion_report
from app.services.platform_journey_evidence_store import (
    get_latest_platform_journey_evidence,
    list_platform_journey_evidence,
)
from app.services.platform_journey_handoff import build_platform_journey_handoff
from app.services.platform_journey_operator import (
    build_platform_journey_operator_console,
    build_platform_journey_readiness_matrix,
)
from app.services.platform_journey_release_readiness import build_platform_journey_release_readiness
from app.services.platform_journey_validation_plan import build_platform_journey_validation_plan
from app.services.platform_journey_views import (
    build_platform_journey_actions,
    build_platform_journey_steps,
    build_platform_journey_summary,
)
from app.services.platform_release_candidate import (
    build_release_artifact_catalog,
    build_release_candidate_checklist,
    build_release_candidate_ci_contract,
    build_release_candidate_command_catalog,
    build_release_candidate_evidence,
    build_release_candidate_gates,
    build_release_candidate_manifest,
    build_release_candidate_readiness,
    build_release_compatibility_matrix,
    build_release_contract,
    build_release_summary,
)

router = APIRouter(prefix="/platform", tags=["platform-diagnostics"])


@router.get("/diagnostics")
def get_platform_diagnostics() -> dict[str, Any]:
    return build_platform_diagnostics()


@router.get("/diagnostics/summary")
def get_platform_diagnostics_summary() -> dict[str, Any]:
    return build_platform_diagnostics_summary()


@router.get("/diagnostics/issues")
def get_platform_diagnostics_issues() -> dict[str, Any]:
    return build_platform_diagnostics_issues()


@router.get("/diagnostics/remediation")
def get_platform_diagnostics_remediation() -> dict[str, Any]:
    return build_platform_diagnostics_remediation()


@router.get("/diagnostics/catalog")
def get_platform_diagnostics_catalog() -> dict[str, Any]:
    return build_platform_diagnostics_catalog()


@router.get("/journey")
def get_platform_journey() -> dict[str, Any]:
    return build_platform_journey()


@router.get("/journey/summary")
def get_platform_journey_summary() -> dict[str, Any]:
    return build_platform_journey_summary()


@router.get("/journey/steps")
def get_platform_journey_steps() -> dict[str, Any]:
    return build_platform_journey_steps()


@router.get("/journey/actions")
def get_platform_journey_actions() -> dict[str, Any]:
    return build_platform_journey_actions()


@router.get("/journey/evidence")
def get_platform_journey_evidence_index(limit: int = 20) -> dict[str, Any]:
    return list_platform_journey_evidence(limit=limit)


@router.get("/journey/evidence/latest")
def get_platform_journey_evidence_latest() -> dict[str, Any]:
    return get_latest_platform_journey_evidence()


@router.get("/journey/bundle")
def get_platform_journey_bundle(evidence_limit: int = 5) -> dict[str, Any]:
    return build_platform_journey_bundle(evidence_limit=evidence_limit)


@router.get("/journey/handoff")
def get_platform_journey_handoff(evidence_limit: int = 5) -> dict[str, Any]:
    return build_platform_journey_handoff(evidence_limit=evidence_limit)


@router.get("/journey/operator-console")
def get_platform_journey_operator_console(evidence_limit: int = 5) -> dict[str, Any]:
    return build_platform_journey_operator_console(evidence_limit=evidence_limit)


@router.get("/journey/readiness-matrix")
def get_platform_journey_readiness_matrix(evidence_limit: int = 5) -> dict[str, Any]:
    return build_platform_journey_readiness_matrix(evidence_limit=evidence_limit)


@router.get("/journey/validation-plan")
def get_platform_journey_validation_plan(evidence_limit: int = 5) -> dict[str, Any]:
    return build_platform_journey_validation_plan(evidence_limit=evidence_limit)


@router.get("/journey/acceptance")
def get_platform_journey_acceptance(evidence_limit: int = 5) -> dict[str, Any]:
    return build_platform_journey_acceptance(evidence_limit=evidence_limit)


@router.get("/journey/release-readiness")
def get_platform_journey_release_readiness(evidence_limit: int = 5) -> dict[str, Any]:
    return build_platform_journey_release_readiness(evidence_limit=evidence_limit)


@router.get("/journey/completion-report")
def get_platform_journey_completion_report(evidence_limit: int = 5) -> dict[str, Any]:
    return build_platform_journey_completion_report(evidence_limit=evidence_limit)


@router.get("/journey/closeout-package")
def get_platform_journey_closeout_package(evidence_limit: int = 5) -> dict[str, Any]:
    return build_platform_journey_closeout_package(evidence_limit=evidence_limit)


@router.get("/journey/closeout-checklist")
def get_platform_journey_closeout_checklist(evidence_limit: int = 5) -> dict[str, Any]:
    return build_platform_journey_closeout_checklist(evidence_limit=evidence_limit)


@router.get("/release-candidate")
def get_platform_release_candidate(evidence_limit: int = 5) -> dict[str, Any]:
    return build_release_candidate_readiness(evidence_limit=evidence_limit)


@router.get("/release-candidate/commands")
def get_platform_release_candidate_commands() -> dict[str, Any]:
    return build_release_candidate_command_catalog()


@router.get("/release-candidate/evidence")
def get_platform_release_candidate_evidence(evidence_limit: int = 5) -> dict[str, Any]:
    return build_release_candidate_evidence(evidence_limit=evidence_limit)


@router.get("/release-candidate/gates")
def get_platform_release_candidate_gates(evidence_limit: int = 5) -> dict[str, Any]:
    return build_release_candidate_gates(evidence_limit=evidence_limit)


@router.get("/release-candidate/checklist")
def get_platform_release_candidate_checklist(evidence_limit: int = 5) -> dict[str, Any]:
    return build_release_candidate_checklist(evidence_limit=evidence_limit)


@router.get("/release-candidate/ci-contract")
def get_platform_release_candidate_ci_contract(evidence_limit: int = 5) -> dict[str, Any]:
    return build_release_candidate_ci_contract(evidence_limit=evidence_limit)


@router.get("/release-candidate/manifest")
def get_platform_release_candidate_manifest(evidence_limit: int = 5) -> dict[str, Any]:
    return build_release_candidate_manifest(evidence_limit=evidence_limit)


@router.get("/release-candidate/contract")
def get_platform_release_candidate_contract(evidence_limit: int = 5) -> dict[str, Any]:
    return build_release_contract(evidence_limit=evidence_limit)


@router.get("/release-candidate/summary")
def get_platform_release_candidate_summary(evidence_limit: int = 5) -> dict[str, Any]:
    return build_release_summary(evidence_limit=evidence_limit)


@router.get("/release-candidate/compatibility")
def get_platform_release_candidate_compatibility(evidence_limit: int = 5) -> dict[str, Any]:
    return build_release_compatibility_matrix(evidence_limit=evidence_limit)


@router.get("/release-candidate/artifacts")
def get_platform_release_candidate_artifacts(evidence_limit: int = 5) -> dict[str, Any]:
    return build_release_artifact_catalog(evidence_limit=evidence_limit)
