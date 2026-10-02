from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.identity.models import IdentityUser
from app.identity.service import normalize_email
from app.models.core import Organization
from app.models.security import Permission, Role, RolePermission

INSTALLATION_ADMIN_PERMISSION_CATALOG = (
    (
        "organization.dashboard",
        "read",
        "Read the selected organization's product dashboard.",
    ),
    (
        "organization.security",
        "read",
        "Read organization-owned access configuration and posture.",
    ),
    (
        "organization.security",
        "administer",
        "Administer organization-owned access configuration.",
    ),
    ("organization.reporting", "read", "Read organization-scoped reporting."),
    ("knowledge_collections", "read", "Read knowledge collection configuration."),
    ("document_configuration", "read", "Read document configuration."),
    (
        "documents",
        "read",
        "Read organization-owned documents and lifecycle state.",
    ),
    (
        "documents",
        "administer",
        "Administer organization-owned documents and lifecycle state.",
    ),
    ("control_plane.health", "read", "Read organization operational health."),
    (
        "control_plane.reconciliation",
        "read",
        "Read artifact reconciliation state.",
    ),
    (
        "control_plane.reconciliation",
        "administer",
        "Run bounded artifact reconciliation.",
    ),
    (
        "control_plane.scheduler",
        "read",
        "Read scheduler jobs, schedules, and runs.",
    ),
    (
        "control_plane.scheduler",
        "administer",
        "Administer scheduler jobs and schedules.",
    ),
    (
        "platform.assistants",
        "read",
        "Read organization-owned assistants and conversations.",
    ),
    (
        "platform.assistants",
        "administer",
        "Operate organization-owned assistants and conversations.",
    ),
    ("ai.configuration", "read", "Read organization AI configuration."),
    (
        "ai.providers",
        "administer",
        "Administer organization AI provider configuration.",
    ),
    (
        "ai.models",
        "administer",
        "Administer organization AI model configuration.",
    ),
    (
        "ai.validation",
        "execute",
        "Validate organization AI provider and model configuration.",
    ),
)

_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ROLE_SUFFIX = "-administrator"


@dataclass(frozen=True)
class InstallationBootstrap:
    organization_name: str
    organization_slug: str
    admin_email: str
    admin_display_name: str | None
    admin_password: str
    language: str | None = None
    timezone: str | None = None


@dataclass(frozen=True)
class InstallationBootstrapResult:
    organization_id: str
    organization_slug: str
    role_id: str
    role_code: str
    user_id: str
    organization_created: bool
    role_created: bool
    user_created: bool


def _normalize_inputs(command: InstallationBootstrap) -> tuple[str, str]:
    name = command.organization_name.strip()
    slug = command.organization_slug.strip().lower()
    if not name:
        raise ValueError("organization name is required")
    if len(name) > 255:
        raise ValueError("organization name exceeds 255 characters")
    if not slug:
        raise ValueError("organization slug is required")
    if len(slug) > 128 or _SLUG_PATTERN.fullmatch(slug) is None:
        raise ValueError(
            "organization slug must use lowercase letters, numbers, and single hyphens"
        )
    return name, slug


def _role_code_for_slug(slug: str) -> str:
    prefix_limit = 128 - len(_ROLE_SUFFIX)
    return f"{slug[:prefix_limit].rstrip('-')}{_ROLE_SUFFIX}"


def _role_name_for_organization(name: str) -> str:
    suffix = " Administrator"
    return f"{name[: 255 - len(suffix)].rstrip()}{suffix}"


def _get_or_create_organization(
    db: Session,
    *,
    name: str,
    slug: str,
) -> tuple[Organization, bool]:
    organization = db.scalar(select(Organization).where(Organization.slug == slug))
    if organization is not None:
        if organization.name != name:
            raise ValueError("organization slug already exists with a different name")
        if organization.status != "active":
            raise ValueError("organization slug already exists but is not active")
        if not bool((organization.config or {}).get("installation_bootstrap")):
            raise ValueError(
                "organization already exists outside the installation bootstrap contract"
            )
        return organization, False

    organization = Organization(
        slug=slug,
        name=name,
        description=None,
        status="active",
        config={"installation_bootstrap": True},
        created_by="installation-bootstrap",
        updated_by="installation-bootstrap",
    )
    db.add(organization)
    db.flush()
    return organization, True


def _get_or_create_permission(
    db: Session,
    *,
    resource: str,
    action: str,
    description: str,
) -> Permission:
    permission = db.scalar(
        select(Permission).where(
            Permission.resource == resource,
            Permission.action == action,
        )
    )
    if permission is None:
        permission = Permission(
            resource=resource,
            action=action,
            description=description,
        )
        db.add(permission)
        db.flush()
    return permission


def _get_or_create_admin_role(
    db: Session,
    organization: Organization,
) -> tuple[Role, bool]:
    role_code = _role_code_for_slug(organization.slug)
    role = db.scalar(
        select(Role).where(
            Role.organization_id == organization.id,
            Role.code == role_code,
        )
    )
    if role is None:
        role = Role(
            organization_id=organization.id,
            code=role_code,
            name=_role_name_for_organization(organization.name),
            description=(
                "Initial organization administrator role created during installation."
            ),
            is_system=False,
            status="active",
            config={"installation_bootstrap": True, "editable": True},
            created_by="installation-bootstrap",
            updated_by="installation-bootstrap",
        )
        db.add(role)
        db.flush()
        return role, True
    if role.status != "active":
        raise ValueError("installation administrator role exists but is not active")
    if not bool((role.config or {}).get("installation_bootstrap")):
        raise ValueError(
            "administrator role code is already used outside the installation bootstrap contract"
        )
    return role, False


def _reconcile_admin_permissions(db: Session, role: Role) -> None:
    for resource, action, description in INSTALLATION_ADMIN_PERMISSION_CATALOG:
        permission = _get_or_create_permission(
            db,
            resource=resource,
            action=action,
            description=description,
        )
        link = db.scalar(
            select(RolePermission).where(
                RolePermission.role_id == role.id,
                RolePermission.permission_id == permission.id,
            )
        )
        if link is None:
            db.add(RolePermission(role_id=role.id, permission_id=permission.id))
            db.flush()


def bootstrap_installation(
    identity_db: Session,
    platform_db: Session,
    settings: Settings,
    command: InstallationBootstrap,
) -> InstallationBootstrapResult:
    from app.services.installation_setup import (
        InstallationBootstrapCommand,
        InstallationSetupService,
    )

    before_organization = platform_db.scalar(
        select(Organization).where(Organization.slug == command.organization_slug.strip().lower())
    )
    before_role = None
    if before_organization is not None:
        before_role = platform_db.scalar(
            select(Role).where(
                Role.organization_id == before_organization.id,
                Role.code == _role_code_for_slug(command.organization_slug.strip().lower()),
            )
        )
    before_user = identity_db.scalar(
        select(IdentityUser).where(IdentityUser.email_normalized == normalize_email(command.admin_email))
    )
    service = InstallationSetupService(
        platform_db,
        identity_db,
        settings,
        actor="installation-bootstrap-cli",
    )
    result = service.bootstrap(
        InstallationBootstrapCommand(
            organization_name=command.organization_name,
            organization_slug=command.organization_slug,
            admin_email=command.admin_email,
            admin_display_name=command.admin_display_name,
            admin_password=command.admin_password,
            language=command.language or settings.installation_default_language,
            timezone=command.timezone or settings.installation_default_timezone,
        )
    )
    evidence = service.persisted_evidence()
    organization_evidence = evidence["organization_configured"]
    administrator_evidence = evidence["administrator_configured"]
    organization_payload = result["details"]["organization_configured"]
    administrator_payload = result["details"]["administrator_configured"]
    return InstallationBootstrapResult(
        organization_id=organization_evidence.resource_id,
        organization_slug=str(organization_payload["slug"]),
        role_id=str(administrator_payload["role_id"]),
        role_code=str(administrator_payload["role_code"]),
        user_id=administrator_evidence.resource_id,
        organization_created=before_organization is None,
        role_created=before_role is None,
        user_created=before_user is None,
    )
