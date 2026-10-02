from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.identity.models import IdentityUser, PasswordCredential
from app.identity.passwords import PasswordManager
from app.identity.service import IdentityService, available_username_from_email, normalize_email
from app.models.audit import AuditEvent
from app.models.security import Permission, Role, RoleAssignment, RolePermission

PLATFORM_IDENTITY_LOCK = 7_241_004


@dataclass(frozen=True)
class PlatformIdentityProvisioning:
    mode: str
    email_display: str
    actor_reference: str
    platform_role_reference: str
    display_name: str | None = None
    password: str | None = None


@dataclass(frozen=True)
class PlatformIdentityProvisioningResult:
    operation: str
    user_id: UUID
    role_id: UUID
    role_code: str
    assignment_id: UUID
    changed_fields: tuple[str, ...]


def _required_text(value: str, field: str, maximum: int) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    if len(normalized) > maximum:
        raise ValueError(f"{field} must contain at most {maximum} characters")
    return normalized


def _platform_role(db: Session, reference: str) -> Role:
    normalized = _required_text(reference, "platform_role_reference", 128)
    try:
        role_id = UUID(normalized)
    except ValueError:
        roles = list(
            db.scalars(
                select(Role).where(
                    Role.organization_id.is_(None),
                    Role.code == normalized,
                )
            ).all()
        )
    else:
        role = db.get(Role, role_id)
        roles = [role] if role is not None and role.organization_id is None else []

    if not roles:
        raise ValueError("platform role does not exist")
    if len(roles) != 1:
        raise ValueError("platform role reference is ambiguous; use its UUID")
    role = roles[0]
    config = role.config if isinstance(role.config, dict) else {}
    if role.status != "active" or role.is_system or config.get("scope") != "platform":
        raise ValueError("platform role is not delegable")
    permission_count = db.scalar(
        select(func.count()).select_from(RolePermission).where(RolePermission.role_id == role.id)
    )
    if not permission_count:
        raise ValueError("platform role is not delegable")
    return role


def _assignment(db: Session, *, user_id: UUID, role: Role, actor_reference: str) -> tuple[RoleAssignment, bool]:
    assignment = db.scalar(
        select(RoleAssignment).where(
            RoleAssignment.organization_id.is_(None),
            RoleAssignment.role_id == role.id,
            RoleAssignment.principal_type == "user",
            RoleAssignment.principal_id == str(user_id),
            RoleAssignment.scope_type == "platform",
            RoleAssignment.scope_id == "platform",
        )
    )
    if assignment is None:
        assignment = RoleAssignment(
            organization_id=None,
            role_id=role.id,
            principal_type="user",
            principal_id=str(user_id),
            scope_type="platform",
            scope_id="platform",
            status="active",
            created_by=actor_reference,
            updated_by=actor_reference,
        )
        db.add(assignment)
        db.flush()
        return assignment, True
    if assignment.status != "active":
        assignment.status = "active"
        assignment.updated_by = actor_reference
        db.flush()
        return assignment, True
    return assignment, False


def _audit(
    db: Session,
    *,
    actor_reference: str,
    user_id: UUID,
    operation: str,
    role: Role,
    assignment_id: UUID,
    changed_fields: list[str],
) -> None:
    db.add(
        AuditEvent(
            organization_id=None,
            actor_type="administrative_cli",
            actor_id=actor_reference,
            resource_type="platform_identity",
            resource_id=str(user_id),
            summary=f"Platform identity {operation} completed.",
            metadata_json={
                "operation": operation,
                "result": "succeeded",
                "role_id": str(role.id),
                "role_code": role.code,
                "assignment_id": str(assignment_id),
                "changed_fields": sorted(changed_fields),
            },
        )
    )


def provision_platform_identity(
    identity_db: Session,
    platform_db: Session,
    settings: Settings,
    command: PlatformIdentityProvisioning,
) -> PlatformIdentityProvisioningResult:
    if command.mode not in {"create", "update"}:
        raise ValueError("mode must be create or update")
    actor_reference = _required_text(command.actor_reference, "actor_reference", 255)
    email_normalized = normalize_email(command.email_display)
    email_display = _required_text(command.email_display, "email", 320)
    display_name = None
    if command.display_name is not None:
        display_name = str(command.display_name).strip() or None
        if display_name is not None and len(display_name) > 255:
            raise ValueError("display_name must contain at most 255 characters")

    platform_db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": PLATFORM_IDENTITY_LOCK})
    identity_db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": PLATFORM_IDENTITY_LOCK})
    role = _platform_role(platform_db, command.platform_role_reference)
    user = identity_db.scalar(select(IdentityUser).where(IdentityUser.email_normalized == email_normalized))
    passwords = PasswordManager(settings)
    changed_fields: list[str] = []

    if command.mode == "create":
        if user is not None:
            raise ValueError("identity already exists; use explicit update mode")
        if command.password is None:
            raise ValueError("password is required in create mode")
        password_hash = passwords.hash_password(command.password)
        user = IdentityUser(
            username=available_username_from_email(identity_db, email_display),
            email_normalized=email_normalized,
            email_display=email_display,
            display_name=display_name,
            status="active",
            must_change_password=True,
        )
        identity_db.add(user)
        identity_db.flush()
        identity_db.add(
            PasswordCredential(
                user_id=user.id,
                password_hash=password_hash,
                algorithm=passwords.algorithm,
                parameters=passwords.parameters,
            )
        )
        # Identity commits first across the two authoritative databases. If the
        # platform commit later fails, the account remains fail-closed without a
        # global grant and can only be reconciled through explicit update mode.
        identity_db.commit()
        changed_fields.extend(("identity", "password_credential"))
    else:
        if user is None:
            raise ValueError("identity does not exist; use create mode")
        if user.status != "active":
            raise ValueError("identity is suspended")
        if command.display_name is not None and user.display_name != display_name:
            user.display_name = display_name
            changed_fields.append("display_name")
        if command.password is not None:
            user = IdentityService(identity_db, settings).lock_user_session_lifecycle(user.id)
            if user is None:
                raise ValueError("identity does not exist; use create mode")
            credential = identity_db.get(PasswordCredential, user.id)
            if credential is None:
                raise ValueError("identity has no password credential")
            credential.password_hash = passwords.hash_password(command.password)
            credential.algorithm = passwords.algorithm
            credential.parameters = passwords.parameters
            credential.password_changed_at = datetime.now(UTC)
            user.must_change_password = True
            IdentityService(identity_db, settings).revoke_user_sessions(
                user,
                reason="password_reset",
                actor_reference=actor_reference,
            )
            changed_fields.append("password_credential")
        identity_db.commit()

    assignment, assignment_changed = _assignment(
        platform_db,
        user_id=user.id,
        role=role,
        actor_reference=actor_reference,
    )
    if assignment_changed:
        changed_fields.append("platform_role_assignment")
    _audit(
        platform_db,
        actor_reference=actor_reference,
        user_id=user.id,
        operation=command.mode,
        role=role,
        assignment_id=assignment.id,
        changed_fields=changed_fields,
    )
    platform_db.commit()
    return PlatformIdentityProvisioningResult(
        operation=command.mode,
        user_id=user.id,
        role_id=role.id,
        role_code=role.code,
        assignment_id=assignment.id,
        changed_fields=tuple(sorted(changed_fields)),
    )


def deactivate_platform_identity(
    identity_db: Session,
    platform_db: Session,
    *,
    email: str,
    platform_role_reference: str,
    actor_reference: str,
) -> PlatformIdentityProvisioningResult:
    actor_reference = _required_text(actor_reference, "actor_reference", 255)
    email_normalized = normalize_email(email)
    platform_db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": PLATFORM_IDENTITY_LOCK})
    identity_db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": PLATFORM_IDENTITY_LOCK})
    role = _platform_role(platform_db, platform_role_reference)
    user = identity_db.scalar(select(IdentityUser).where(IdentityUser.email_normalized == email_normalized))
    if user is None:
        raise ValueError("identity does not exist")
    assignment = platform_db.scalar(
        select(RoleAssignment).where(
            RoleAssignment.organization_id.is_(None),
            RoleAssignment.role_id == role.id,
            RoleAssignment.principal_type == "user",
            RoleAssignment.principal_id == str(user.id),
            RoleAssignment.scope_type == "platform",
            RoleAssignment.scope_id == "platform",
        )
    )
    if assignment is None:
        raise ValueError("platform role assignment does not exist")

    now = datetime.now(UTC)
    changed_fields: list[str] = []
    user = IdentityService(identity_db, get_settings()).lock_user_session_lifecycle(user.id)
    if user is None:
        raise ValueError("identity does not exist")
    if user.status != "suspended":
        user.status = "suspended"
        user.disabled_at = now
        changed_fields.append("identity_status")
    revoked_session_count = IdentityService(identity_db, get_settings()).revoke_user_sessions(
        user,
        reason="identity_deactivated",
        actor_reference=actor_reference,
    )
    if revoked_session_count:
        changed_fields.append("active_sessions")
    identity_db.commit()

    if assignment.status != "inactive":
        assignment.status = "inactive"
        assignment.updated_by = actor_reference
        changed_fields.append("platform_role_assignment")
    _audit(
        platform_db,
        actor_reference=actor_reference,
        user_id=user.id,
        operation="deactivate",
        role=role,
        assignment_id=assignment.id,
        changed_fields=changed_fields,
    )
    platform_db.commit()
    return PlatformIdentityProvisioningResult(
        operation="deactivate",
        user_id=user.id,
        role_id=role.id,
        role_code=role.code,
        assignment_id=assignment.id,
        changed_fields=tuple(sorted(changed_fields)),
    )


def promote_platform_administrator(
    identity_db: Session,
    platform_db: Session,
    *,
    username: str,
    platform_role_reference: str,
    actor_reference: str,
) -> PlatformIdentityProvisioningResult:
    """Idempotently grant an existing identity an administrative platform role."""
    actor_reference = _required_text(actor_reference, "actor_reference", 255)
    normalized_username = _required_text(username, "username", 128).casefold()
    platform_db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": PLATFORM_IDENTITY_LOCK})
    identity_db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": PLATFORM_IDENTITY_LOCK})
    user = identity_db.scalar(select(IdentityUser).where(IdentityUser.username == normalized_username))
    if user is None:
        raise ValueError("identity does not exist")
    if user.status != "active":
        raise ValueError("identity is suspended")
    role = _platform_role(platform_db, platform_role_reference)
    grants_administration = platform_db.scalar(
        select(RolePermission.id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(
            RolePermission.role_id == role.id,
            Permission.resource == "platform.security",
            Permission.action == "administer",
        )
        .limit(1)
    )
    if grants_administration is None:
        raise ValueError("selected role does not grant platform.security:administer")
    assignment, changed = _assignment(
        platform_db,
        user_id=user.id,
        role=role,
        actor_reference=actor_reference,
    )
    changed_fields = ["platform_role_assignment"] if changed else []
    _audit(
        platform_db,
        actor_reference=actor_reference,
        user_id=user.id,
        operation="promote_administrator",
        role=role,
        assignment_id=assignment.id,
        changed_fields=changed_fields,
    )
    platform_db.commit()
    return PlatformIdentityProvisioningResult(
        operation="promote_administrator",
        user_id=user.id,
        role_id=role.id,
        role_code=role.code,
        assignment_id=assignment.id,
        changed_fields=tuple(changed_fields),
    )
