from fastapi import APIRouter, Depends

from app.api.dependencies.authentication import require_api_access
from app.api.routes.ai import router as ai_router
from app.api.routes.ai_configuration import router as ai_configuration_router
from app.api.routes.ai_studio import router as ai_studio_router
from app.api.routes.assistant_workspace import router as assistant_workspace_router
from app.api.routes.assistants import router as assistants_router
from app.api.routes.capacity import router as capacity_router
from app.api.routes.connector_workspace import router as connector_workspace_router
from app.api.routes.connectors import router as connectors_router
from app.api.routes.core import router as core_router
from app.api.routes.document_binary_uploads import router as document_binary_uploads_router
from app.api.routes.document_ingestion import router as document_ingestion_router
from app.api.routes.document_lifecycle import router as document_lifecycle_router
from app.api.routes.document_organization_associations import (
    router as document_organization_associations_router,
)
from app.api.routes.document_registration_execution import router as document_registration_execution_router
from app.api.routes.document_review_runtime import router as document_review_runtime_router
from app.api.routes.document_reviews import router as document_reviews_router
from app.api.routes.document_versions import router as document_versions_router
from app.api.routes.document_workspace import router as document_workspace_router
from app.api.routes.documents import router as documents_router
from app.api.routes.enterprise_api_integration import router as enterprise_api_integration_router
from app.api.routes.enterprise_search import router as enterprise_search_router
from app.api.routes.feedback_audit import router as feedback_audit_router
from app.api.routes.governance_center import router as governance_center_router
from app.api.routes.indexing import router as indexing_router
from app.api.routes.ingestion import router as ingestion_router
from app.api.routes.knowledge import router as knowledge_router
from app.api.routes.knowledge_collections import router as knowledge_collections_router
from app.api.routes.knowledge_workspace import router as knowledge_workspace_router
from app.api.routes.model_provider_center import router as model_provider_center_router
from app.api.routes.observability import router as observability_router
from app.api.routes.operational_health import router as operational_health_router
from app.api.routes.operational_observability import router as operational_observability_router
from app.api.routes.operations_center import router as operations_center_router
from app.api.routes.organization_access import router as organization_access_router
from app.api.routes.organization_structure import router as organization_structure_router
from app.api.routes.platform_administration import router as platform_administration_router
from app.api.routes.platform_dashboard import router as platform_dashboard_router
from app.api.routes.platform_diagnostics import router as platform_diagnostics_router
from app.api.routes.platform_operations import router as platform_operations_router
from app.api.routes.platform_security_sessions import router as platform_security_sessions_router
from app.api.routes.portal_acceptance import router as portal_acceptance_router
from app.api.routes.product_acceptance import router as product_acceptance_router
from app.api.routes.product_integration import router as product_integration_router
from app.api.routes.production_acceptance import router as production_acceptance_router
from app.api.routes.reconciliation import router as control_plane_router
from app.api.routes.recovery import router as recovery_router
from app.api.routes.recovery_authoritative import router as recovery_authoritative_router
from app.api.routes.reference_tenant import router as reference_tenant_router
from app.api.routes.release_governance import router as release_governance_router
from app.api.routes.reporting_analytics import router as reporting_analytics_router
from app.api.routes.runtime import router as runtime_router
from app.api.routes.runtime_executions import router as runtime_executions_router
from app.api.routes.runtime_persistence import router as runtime_persistence_router
from app.api.routes.runtime_workers import router as runtime_workers_router
from app.api.routes.scheduler import router as scheduler_router
from app.api.routes.scheduler_background_services import router as scheduler_background_services_router
from app.api.routes.scheduler_commands import router as scheduler_commands_router
from app.api.routes.search_discovery import router as search_discovery_router
from app.api.routes.security import router as security_router
from app.api.routes.security_acceptance import router as security_acceptance_router
from app.api.routes.security_center import router as security_center_router
from app.api.routes.security_management import router as security_management_router
from app.api.routes.smoke import router as smoke_router
from app.api.routes.storage_execution import router as storage_execution_router
from app.api.routes.workflow_studio import router as workflow_studio_router
from app.api.routes.workflows import router as workflows_router

api_router = APIRouter(prefix="/api", dependencies=[Depends(require_api_access)])
api_router.include_router(assistant_workspace_router)
api_router.include_router(assistants_router)
api_router.include_router(capacity_router)
api_router.include_router(core_router)
api_router.include_router(document_workspace_router)
api_router.include_router(document_organization_associations_router)
api_router.include_router(documents_router)
api_router.include_router(document_registration_execution_router)
api_router.include_router(document_versions_router)
api_router.include_router(document_binary_uploads_router)
api_router.include_router(document_ingestion_router)
api_router.include_router(document_lifecycle_router)
api_router.include_router(document_reviews_router)
api_router.include_router(document_review_runtime_router)
api_router.include_router(security_router)
api_router.include_router(security_management_router)
api_router.include_router(organization_access_router)
api_router.include_router(organization_structure_router)
api_router.include_router(connector_workspace_router)
api_router.include_router(connectors_router)
api_router.include_router(ai_studio_router)
api_router.include_router(ai_configuration_router)
api_router.include_router(ai_router)
api_router.include_router(runtime_router)
api_router.include_router(runtime_persistence_router)
api_router.include_router(runtime_executions_router)
api_router.include_router(runtime_workers_router)
api_router.include_router(ingestion_router)
api_router.include_router(indexing_router)
api_router.include_router(knowledge_router)
api_router.include_router(knowledge_collections_router)
api_router.include_router(knowledge_workspace_router)
api_router.include_router(model_provider_center_router)
api_router.include_router(observability_router)
api_router.include_router(enterprise_api_integration_router)
api_router.include_router(enterprise_search_router)
api_router.include_router(feedback_audit_router)
api_router.include_router(governance_center_router)
api_router.include_router(reference_tenant_router)
api_router.include_router(recovery_router)
api_router.include_router(recovery_authoritative_router)
api_router.include_router(release_governance_router)
api_router.include_router(reporting_analytics_router)
api_router.include_router(control_plane_router)
api_router.include_router(operational_health_router)
api_router.include_router(operations_center_router)
api_router.include_router(operational_observability_router)
api_router.include_router(platform_administration_router)
api_router.include_router(platform_dashboard_router)
api_router.include_router(platform_diagnostics_router)
api_router.include_router(platform_operations_router)
api_router.include_router(platform_security_sessions_router)
api_router.include_router(portal_acceptance_router)
api_router.include_router(product_acceptance_router)
api_router.include_router(product_integration_router)
api_router.include_router(production_acceptance_router)
api_router.include_router(scheduler_router)
api_router.include_router(scheduler_background_services_router)
api_router.include_router(scheduler_commands_router)
api_router.include_router(search_discovery_router)
api_router.include_router(security_acceptance_router)
api_router.include_router(security_center_router)
api_router.include_router(smoke_router)
api_router.include_router(storage_execution_router)
api_router.include_router(workflow_studio_router)
api_router.include_router(workflows_router)
