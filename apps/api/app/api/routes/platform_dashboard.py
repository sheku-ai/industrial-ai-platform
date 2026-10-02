from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies.authentication import get_authenticated_principal
from app.api.dependencies.runtime_context import RuntimeRequestContext, get_runtime_context
from app.db.session import get_db
from app.identity.contracts import AuthenticatedPrincipal
from app.schemas.platform_dashboard import PlatformDashboardRuntimeResponse
from app.security.resource_scope import ResourceScope
from app.services.authorization import AuthorizationService
from app.services.platform_dashboard_runtime import build_platform_dashboard_runtime

router = APIRouter(prefix="/platform/dashboard", tags=["platform-dashboard"])


@router.get("/capabilities")
def get_platform_navigation_capabilities(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    principal: AuthenticatedPrincipal = Depends(get_authenticated_principal),
    db: Session = Depends(get_db),
):
    organization_scoped = context.organization_id is not None
    platform_permissions = AuthorizationService(db).resolve_permissions_for_scope(
        resource_scope=ResourceScope.platform(),
        principal_id=principal.actor_reference,
        principal_type="user",
        # Global assignments are independent from organization memberships.
        allowed_role_ids=None,
    )
    return {
        "organization_id": str(context.organization_id) if context.organization_id else None,
        "documents": {
            "visible": organization_scoped and context.has_permission("documents", "read"),
            "action_available": organization_scoped and context.has_permission("documents", "administer"),
        },
        "search": {
            "visible": organization_scoped and context.has_permission("knowledge_collections", "read"),
            "action_available": organization_scoped and context.has_permission("knowledge_collections", "read"),
        },
        "assistant": {
            "visible": organization_scoped and context.has_permission("platform.assistants", "read"),
            "action_available": organization_scoped and context.has_permission("platform.assistants", "administer"),
        },
        "ai_configuration": {
            "visible": organization_scoped and context.has_permission("ai.configuration", "read"),
            "administer_providers": organization_scoped
            and context.has_permission("ai.providers", "administer"),
            "administer_models": organization_scoped
            and context.has_permission("ai.models", "administer"),
            "validate": organization_scoped
            and context.has_permission("ai.validation", "execute"),
        },
        "platform": {
            "operations": {
                "visible": "platform.operations:read" in platform_permissions,
                "action_available": "platform.operations:administer" in platform_permissions,
            },
            "scheduler": {
                "visible": (
                    "platform.operations:read" in platform_permissions
                    and context.has_permission("control_plane.scheduler", "read")
                ),
                "action_available": (
                    "platform.operations:administer" in platform_permissions
                    and context.has_permission("control_plane.scheduler", "administer")
                ),
            },
            "release_readiness": {
                "visible": "platform.production_acceptance:read" in platform_permissions,
                "action_available": "platform.production_acceptance:administer" in platform_permissions,
            },
        },
    }


@router.get("/runtime", response_model=PlatformDashboardRuntimeResponse)
def get_platform_dashboard_runtime(
    context: RuntimeRequestContext = Depends(get_runtime_context),
    db: Session = Depends(get_db),
):
    return build_platform_dashboard_runtime(
        db,
        organization_id=context.organization_id,
        platform_scope=context.scope_type == "platform",
        permissions=context.permissions,
    )
