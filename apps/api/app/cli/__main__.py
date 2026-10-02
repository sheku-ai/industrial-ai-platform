from __future__ import annotations

import argparse
import getpass
import os
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.identity.bootstrap import InitialAdminBootstrap, bootstrap_initial_admin
from app.identity.db import IdentitySessionLocal
from app.identity.installation_bootstrap import (
    InstallationBootstrap,
    bootstrap_installation,
)
from app.identity.models import AuthSession, IdentityUser
from app.identity.passwords import PasswordPolicyError
from app.identity.platform_provisioning import (
    PlatformIdentityProvisioning,
    deactivate_platform_identity,
    promote_platform_administrator,
    provision_platform_identity,
)
from app.identity.service import IdentityService
from app.services.community_intent_model_bootstrap import bootstrap_community_intent_model
from app.services.installation_setup import InstallationSetupService
from app.services.reference_tenant import reconcile_reference_tenant_permissions


def _prompt_uuid(label: str) -> uuid.UUID:
    raw = input(f"{label}: ").strip()
    try:
        value = uuid.UUID(raw)
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid UUID") from exc
    if value.int == 0:
        raise ValueError(f"{label} must not be empty")
    return value


def _prompt_password() -> str:
    password = getpass.getpass("Password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise ValueError("password confirmation does not match")
    return password


def create_initial_admin() -> int:
    settings = get_settings()
    if IdentitySessionLocal is None:
        raise RuntimeError("IDENTITY_DATABASE_URL is required")
    if SessionLocal is None:
        raise RuntimeError("DATABASE_URL is required to validate organization and role")

    email_display = input("Email: ").strip()
    display_name = input("Display name (optional): ").strip() or None
    password = _prompt_password()
    organization_id = _prompt_uuid("Organization UUID")
    role_id = _prompt_uuid("Organization administrative role UUID")

    platform_db = SessionLocal()
    identity_db = IdentitySessionLocal()
    try:
        result = bootstrap_initial_admin(
            identity_db,
            platform_db,
            settings,
            InitialAdminBootstrap(
                email_display=email_display,
                display_name=display_name,
                password=password,
                organization_id=organization_id,
                role_id=role_id,
            ),
        )
        print(
            "Initial administrator is ready "
            f"(user_id={result.user_id}, organization_id={organization_id}, role_id={role_id})."
        )
        return 0
    except Exception:
        identity_db.rollback()
        platform_db.rollback()
        raise
    finally:
        identity_db.close()
        platform_db.close()


def bootstrap_clean_installation(args: argparse.Namespace) -> int:
    settings = get_settings()
    if IdentitySessionLocal is None:
        raise RuntimeError("IDENTITY_DATABASE_URL is required")
    if SessionLocal is None:
        raise RuntimeError("DATABASE_URL is required")
    password = _password_from_environment(args.password_env, required=True)
    if password is None:
        raise ValueError("installation administrator password is required")

    platform_db = SessionLocal()
    identity_db = IdentitySessionLocal()
    try:
        result = bootstrap_installation(
            identity_db,
            platform_db,
            settings,
            InstallationBootstrap(
                organization_name=args.organization_name,
                organization_slug=args.organization_slug,
                admin_email=args.admin_email,
                admin_display_name=args.admin_display_name,
                admin_password=password,
                language=args.language,
                timezone=args.timezone,
            ),
        )
        print(
            "Installation bootstrap completed "
            f"(organization_id={result.organization_id}, "
            f"organization_slug={result.organization_slug}, "
            f"role_id={result.role_id}, user_id={result.user_id}, "
            f"organization_created={result.organization_created}, "
            f"role_created={result.role_created}, user_created={result.user_created})."
        )
        return 0
    except Exception:
        identity_db.rollback()
        platform_db.rollback()
        raise
    finally:
        identity_db.close()
        platform_db.close()


def reconcile_installation_platform_owner() -> int:
    settings = get_settings()
    if IdentitySessionLocal is None:
        raise RuntimeError("IDENTITY_DATABASE_URL is required")
    if SessionLocal is None:
        raise RuntimeError("DATABASE_URL is required")

    platform_db = SessionLocal()
    identity_db = IdentitySessionLocal()
    try:
        result = InstallationSetupService(
            platform_db,
            identity_db,
            settings,
            actor="installation-platform-owner-reconciliation-cli",
        ).reconcile_completed_platform_owner()
        print(
            "Completed installation platform owner reconciled "
            f"(installation_setup_id={result['installation_setup_id']}, "
            f"user_id={result['user_id']}, platform_role_id={result['platform_role_id']}, "
            f"platform_assignment_id={result['platform_assignment_id']}, state={result['state']})."
        )
        return 0
    except Exception:
        identity_db.rollback()
        platform_db.rollback()
        raise
    finally:
        identity_db.close()
        platform_db.close()


def reconcile_reference_access() -> int:
    if SessionLocal is None:
        raise RuntimeError("DATABASE_URL is required to reconcile persisted access")

    platform_db = SessionLocal()
    try:
        result = reconcile_reference_tenant_permissions(
            platform_db,
            requested_by="reconcile-reference-access",
        )
        print(
            "Reference access permissions reconciled "
            f"(roles={result['roles_reconciled']}, "
            f"permissions_created={result['permissions_created']}, "
            f"role_permissions_created={result['role_permissions_created']})."
        )
        return 0
    except Exception:
        platform_db.rollback()
        raise
    finally:
        platform_db.close()


def bootstrap_community_intent() -> int:
    if SessionLocal is None:
        raise RuntimeError("DATABASE_URL is required to register the Community intent model")
    platform_db = SessionLocal()
    try:
        result = bootstrap_community_intent_model(platform_db)
        platform_db.commit()
        print(
            "Community intent model bootstrap completed "
            f"(intent_model_id={result.model.intent_model_id}, "
            f"model_version={result.model.model_version}, reused={result.reused})."
        )
        return 0
    except Exception:
        platform_db.rollback()
        raise
    finally:
        platform_db.close()


def _password_from_environment(variable_name: str | None, *, required: bool) -> str | None:
    if not variable_name:
        if required:
            raise ValueError("--password-env is required in create mode")
        return None
    value = os.environ.get(variable_name)
    if value is None:
        raise ValueError(f"password environment variable {variable_name!r} is not set")
    return value


def provision_platform_access(args: argparse.Namespace) -> int:
    settings = get_settings()
    if IdentitySessionLocal is None:
        raise RuntimeError("IDENTITY_DATABASE_URL is required")
    if SessionLocal is None:
        raise RuntimeError("DATABASE_URL is required")
    password = _password_from_environment(
        args.password_env,
        required=args.mode == "create",
    )
    platform_db = SessionLocal()
    identity_db = IdentitySessionLocal()
    try:
        result = provision_platform_identity(
            identity_db,
            platform_db,
            settings,
            PlatformIdentityProvisioning(
                mode=args.mode,
                email_display=args.email,
                display_name=args.display_name,
                password=password,
                platform_role_reference=args.platform_role,
                actor_reference=args.actor_reference,
            ),
        )
        print(
            "Platform identity provisioning completed "
            f"(operation={result.operation}, user_id={result.user_id}, "
            f"role_id={result.role_id}, assignment_id={result.assignment_id}, "
            f"changed_fields={','.join(result.changed_fields) or 'none'})."
        )
        return 0
    except Exception:
        identity_db.rollback()
        platform_db.rollback()
        raise
    finally:
        identity_db.close()
        platform_db.close()


def deactivate_platform_access(args: argparse.Namespace) -> int:
    if IdentitySessionLocal is None:
        raise RuntimeError("IDENTITY_DATABASE_URL is required")
    if SessionLocal is None:
        raise RuntimeError("DATABASE_URL is required")
    platform_db = SessionLocal()
    identity_db = IdentitySessionLocal()
    try:
        result = deactivate_platform_identity(
            identity_db,
            platform_db,
            email=args.email,
            platform_role_reference=args.platform_role,
            actor_reference=args.actor_reference,
        )
        print(
            "Platform identity deactivation completed "
            f"(user_id={result.user_id}, role_id={result.role_id}, "
            f"assignment_id={result.assignment_id}, "
            f"changed_fields={','.join(result.changed_fields) or 'none'})."
        )
        return 0
    except Exception:
        identity_db.rollback()
        platform_db.rollback()
        raise
    finally:
        identity_db.close()
        platform_db.close()


def promote_platform_admin(args: argparse.Namespace) -> int:
    if IdentitySessionLocal is None:
        raise RuntimeError("IDENTITY_DATABASE_URL is required")
    if SessionLocal is None:
        raise RuntimeError("DATABASE_URL is required")
    platform_db = SessionLocal()
    identity_db = IdentitySessionLocal()
    try:
        result = promote_platform_administrator(
            identity_db,
            platform_db,
            username=args.username,
            platform_role_reference=args.platform_role,
            actor_reference=args.actor_reference,
        )
        print(
            "Platform administrator promotion completed "
            f"(user_id={result.user_id}, role_id={result.role_id}, "
            f"assignment_id={result.assignment_id}, "
            f"changed_fields={','.join(result.changed_fields) or 'none'})."
        )
        return 0
    except Exception:
        identity_db.rollback()
        platform_db.rollback()
        raise
    finally:
        identity_db.close()
        platform_db.close()


def purge_auth_sessions(args: argparse.Namespace) -> int:
    if IdentitySessionLocal is None:
        raise RuntimeError("IDENTITY_DATABASE_URL is required")
    identity_db = IdentitySessionLocal()
    try:
        count = IdentityService(identity_db, get_settings()).purge_historical_sessions(
            execute=args.execute,
        )
        action = "purged" if args.execute else "eligible"
        print(f"Historical authentication session cleanup completed ({action}={count}).")
        return 0
    except Exception:
        identity_db.rollback()
        raise
    finally:
        identity_db.close()


def revoke_auth_sessions(args: argparse.Namespace) -> int:
    if IdentitySessionLocal is None:
        raise RuntimeError("IDENTITY_DATABASE_URL is required")
    identity_db = IdentitySessionLocal()
    try:
        user = identity_db.get(IdentityUser, args.user_id)
        if user is None:
            raise ValueError("identity does not exist")
        service = IdentityService(identity_db, get_settings())
        sessions = list(identity_db.scalars(select(AuthSession).where(AuthSession.user_id == user.id)).all())
        eligible_count = sum(item.revoked_at is None for item in sessions)
        if not args.execute:
            print(f"Authentication session revocation preview completed (eligible={eligible_count}).")
            return 0
        service.lock_user_session_lifecycle(user.id)
        revoked_count = service.revoke_user_sessions(
            user,
            reason="administrative_revocation",
            actor_reference=args.actor_reference,
        )
        identity_db.commit()
        print(f"Authentication session revocation completed (revoked={revoked_count}).")
        return 0
    except Exception:
        identity_db.rollback()
        raise
    finally:
        identity_db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Industrial AI Platform administrative CLI")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser(
        "create-initial-admin",
        help="Create or resume the first local administrator bootstrap",
    )
    installation = subcommands.add_parser(
        "bootstrap-installation",
        help=("Create or resume the initial organization and administrator for a clean installation"),
    )
    installation.add_argument("--organization-name", required=True)
    installation.add_argument("--organization-slug", required=True)
    installation.add_argument("--admin-email", required=True)
    installation.add_argument("--admin-display-name")
    installation.add_argument("--language")
    installation.add_argument("--timezone")
    installation.add_argument(
        "--password-env",
        required=True,
        help=("Name of the environment variable containing the installation administrator password"),
    )
    subcommands.add_parser(
        "reconcile-installation-platform-owner",
        help="Idempotently reconcile platform owner authority for a completed installation",
    )
    subcommands.add_parser(
        "reconcile-reference-access",
        help="Idempotently reconcile the persisted canonical organization access catalog",
    )
    subcommands.add_parser(
        "bootstrap-community-intent-model",
        help="Idempotently register the packaged Community SetFit intent model",
    )
    provision = subcommands.add_parser(
        "provision-platform-identity",
        help="Create or explicitly update an authenticable identity with an existing platform role",
    )
    provision.add_argument("--mode", choices=("create", "update"), required=True)
    provision.add_argument("--email", required=True)
    provision.add_argument("--display-name")
    provision.add_argument(
        "--password-env",
        help="Name of the environment variable containing the initial or replacement password",
    )
    provision.add_argument(
        "--platform-role",
        required=True,
        help="UUID or unique code of an existing active, delegable platform role",
    )
    provision.add_argument("--actor-reference", required=True)
    deactivate = subcommands.add_parser(
        "deactivate-platform-identity",
        help="Suspend an identity, revoke its sessions, and deactivate one platform role assignment",
    )
    deactivate.add_argument("--email", required=True)
    deactivate.add_argument("--platform-role", required=True)
    deactivate.add_argument("--actor-reference", required=True)
    promote = subcommands.add_parser(
        "promote-platform-administrator",
        help="Idempotently grant an existing username an administrative platform role",
    )
    promote.add_argument("--username", required=True)
    promote.add_argument("--platform-role", required=True)
    promote.add_argument("--actor-reference", required=True)
    purge = subcommands.add_parser(
        "purge-auth-sessions",
        help="Inspect or purge expired/revoked sessions beyond the persisted retention policy",
    )
    purge.add_argument(
        "--execute",
        action="store_true",
        help="Delete eligible historical sessions; omitted mode is a read-only preview",
    )
    revoke = subcommands.add_parser(
        "revoke-auth-sessions",
        help="Preview or revoke all sessions for one persisted identity",
    )
    revoke.add_argument("--user-id", required=True, type=uuid.UUID)
    revoke.add_argument("--actor-reference", required=True)
    revoke.add_argument(
        "--execute",
        action="store_true",
        help="Persist the revocation; omitted mode is a read-only preview",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "create-initial-admin":
            return create_initial_admin()
        if args.command == "bootstrap-installation":
            return bootstrap_clean_installation(args)
        if args.command == "reconcile-installation-platform-owner":
            return reconcile_installation_platform_owner()
        if args.command == "reconcile-reference-access":
            return reconcile_reference_access()
        if args.command == "bootstrap-community-intent-model":
            return bootstrap_community_intent()
        if args.command == "provision-platform-identity":
            return provision_platform_access(args)
        if args.command == "deactivate-platform-identity":
            return deactivate_platform_access(args)
        if args.command == "promote-platform-administrator":
            return promote_platform_admin(args)
        if args.command == "purge-auth-sessions":
            return purge_auth_sessions(args)
        if args.command == "revoke-auth-sessions":
            return revoke_auth_sessions(args)
    except SQLAlchemyError:
        if args.command == "provision-platform-identity":
            detail = (
                "identity state may already be fail-closed; inspect the persisted audit and "
                "retry only with an explicit mode appropriate to the observed state"
            )
        else:
            detail = "the command is safe to retry with the same inputs"
        print(
            f"{args.command} failed because a database operation was unavailable or rejected; {detail}",
            file=sys.stderr,
        )
        return 1
    except (PasswordPolicyError, ValueError, RuntimeError) as exc:
        print(f"{args.command} failed: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
