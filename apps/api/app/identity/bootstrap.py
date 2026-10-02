from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.identity.models import (
    AuthenticationEvent,
    IdentityUser,
    OrganizationMembership,
    PasswordCredential,
)
from app.identity.passwords import PasswordContext, PasswordManager
from app.identity.service import available_username_from_email, normalize_email
from app.models.core import Organization
from app.models.security import Permission, Role, RoleAssignment, RolePermission


@dataclass(frozen=True)
class InitialAdminBootstrap:
    email_display: str
    display_name: str | None
    password: str
    organization_id: uuid.UUID
    role_id: uuid.UUID


@dataclass(frozen=True)
class InitialAdminBootstrapResult:
    user_id: uuid.UUID
    organization_id: uuid.UUID
    role_id: uuid.UUID
    created_user: bool


def bootstrap_initial_admin(
    identity_db: Session,
    platform_db: Session,
    settings: Settings,
    command: InitialAdminBootstrap,
) -> InitialAdminBootstrapResult:
    email_normalized = normalize_email(command.email_display)
    password_manager = PasswordManager(settings)
    organization = platform_db.get(Organization, command.organization_id)
    if organization is None or organization.status != "active":
        raise ValueError("target organization does not exist or is not active")
    password_context = PasswordContext(
        email=command.email_display,
        display_name=command.display_name,
        organization_name=organization.name,
        organization_slug=organization.slug,
    )
    password_manager.validate_password(command.password, context=password_context)

    role = platform_db.get(Role, command.role_id)
    if role is None or role.status != "active":
        raise ValueError("administrative role does not exist or is not active")
    if role.organization_id != command.organization_id:
        raise ValueError("administrative role must belong to the target organization")
    administrative_permission = platform_db.scalar(
        select(Permission.id)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(
            RolePermission.role_id == role.id,
            Permission.action == "administer",
        )
        .limit(1)
    )
    if administrative_permission is None:
        raise ValueError("selected role has no configured administrative permission")

    identity_db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": 7_241_001})
    users = list(identity_db.scalars(select(IdentityUser).order_by(IdentityUser.created_at)).all())
    user = identity_db.scalar(
        select(IdentityUser).where(IdentityUser.email_normalized == email_normalized)
    )
    created_user = False
    if users and user is None:
        raise ValueError("Identity has already been initialized with a different user")
    if user is None:
        user = IdentityUser(
            username=available_username_from_email(identity_db, command.email_display),
            email_normalized=email_normalized,
            email_display=command.email_display,
            display_name=command.display_name,
            status="active",
            must_change_password=False,
        )
        identity_db.add(user)
        identity_db.flush()
        identity_db.add(
            PasswordCredential(
                user_id=user.id,
                password_hash=password_manager.hash_password(
                    command.password,
                    context=password_context,
                ),
                algorithm=password_manager.algorithm,
                parameters=password_manager.parameters,
            )
        )
        created_user = True
    else:
        credential = identity_db.get(PasswordCredential, user.id)
        if credential is None or not password_manager.verify(
            credential.password_hash, command.password
        ).valid:
            raise ValueError("existing bootstrap identity is incompatible")
        if user.status != "active":
            raise ValueError("existing bootstrap identity is suspended")

    memberships = list(
        identity_db.scalars(
            select(OrganizationMembership).where(OrganizationMembership.user_id == user.id)
        ).all()
    )
    membership = next(
        (
            item
            for item in memberships
            if item.organization_id == command.organization_id and item.role_id == command.role_id
        ),
        None,
    )
    replacement_membership = None
    if memberships and membership is None:
        if len(memberships) != 1 or memberships[0].organization_id != command.organization_id:
            raise ValueError("existing bootstrap membership is incompatible")
        replacement_membership = memberships[0]
        if replacement_membership.status != "active":
            raise ValueError("existing bootstrap membership is suspended")
    if membership is None:
        if replacement_membership is None:
            membership = OrganizationMembership(
                user_id=user.id,
                organization_id=command.organization_id,
                role_id=command.role_id,
                status="active",
            )
            identity_db.add(membership)
    elif membership.status != "active":
        raise ValueError("existing bootstrap membership is suspended")

    # There is no distributed transaction between databases. Identity is committed
    # first for new identities. Access reconciliation commits platform grants first
    # so an interrupted retry remains fail-closed and resumable.
    if replacement_membership is None:
        identity_db.commit()

    platform_db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": 7_241_002})
    assignment = platform_db.scalar(
        select(RoleAssignment).where(
            RoleAssignment.role_id == command.role_id,
            RoleAssignment.principal_type == "user",
            RoleAssignment.principal_id == str(user.id),
        )
    )
    if assignment is None:
        platform_db.add(
            RoleAssignment(
                organization_id=command.organization_id,
                role_id=command.role_id,
                principal_type="user",
                principal_id=str(user.id),
                scope_type="organization",
                scope_id=str(command.organization_id),
                status="active",
            )
        )
    elif (
        assignment.organization_id != command.organization_id
        or assignment.scope_type != "organization"
        or assignment.scope_id != str(command.organization_id)
    ):
        raise ValueError("existing organization role assignment is incompatible")
    elif assignment.status != "active":
        assignment.status = "active"
        platform_db.add(assignment)

    if replacement_membership is not None:
        previous_assignments = list(
            platform_db.scalars(
                select(RoleAssignment).where(
                    RoleAssignment.role_id == replacement_membership.role_id,
                    RoleAssignment.principal_type == "user",
                    RoleAssignment.principal_id == str(user.id),
                    RoleAssignment.status == "active",
                )
            ).all()
        )
        for previous_assignment in previous_assignments:
            previous_assignment.status = "inactive"
            platform_db.add(previous_assignment)
    platform_db.commit()

    if replacement_membership is not None:
        replacement_membership.role_id = command.role_id
        identity_db.add(replacement_membership)
        identity_db.add(
            AuthenticationEvent(
                user_id=user.id,
                email_normalized=user.email_normalized,
                event_type="bootstrap_admin_access_reconciled",
                success=True,
                reason_code="organization_role_replaced",
            )
        )
        identity_db.commit()

    existing_event = identity_db.scalar(
        select(AuthenticationEvent.id).where(
            AuthenticationEvent.event_type == "bootstrap_admin_created",
            AuthenticationEvent.user_id == user.id,
            AuthenticationEvent.success.is_(True),
        )
    )
    if existing_event is None:
        identity_db.add(
            AuthenticationEvent(
                user_id=user.id,
                email_normalized=user.email_normalized,
                event_type="bootstrap_admin_created",
                success=True,
                reason_code="created" if created_user else "resumed",
            )
        )
        identity_db.commit()

    return InitialAdminBootstrapResult(
        user_id=user.id,
        organization_id=command.organization_id,
        role_id=command.role_id,
        created_user=created_user,
    )
