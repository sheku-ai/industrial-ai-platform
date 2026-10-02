from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.identity.bootstrap import InitialAdminBootstrap, bootstrap_initial_admin
from app.identity.models import IdentityUser, OrganizationMembership
from app.identity.passwords import PasswordPolicyError
from app.models.audit import AuditEvent
from app.models.core import Organization
from app.models.installation import (
    InstallationCompletionEvidence,
    InstallationSetup,
    InstallationSetupEvidence,
)
from app.models.runtime_configuration import RuntimeConfiguration, RuntimeConfigurationRevision
from app.models.security import Permission, Role, RoleAssignment, RolePermission
from app.security.platform_roles import (
    PLATFORM_ADMIN_PERMISSION_CATALOG,
    PLATFORM_OWNER_ROLE_CODE,
    reconcile_platform_owner_assignment,
    reconcile_platform_owner_role,
)

SETUP_SCHEMA_VERSION = 1
SETUP_LOCK_KEY = 7_241_005
EVIDENCE_TYPES = (
    "organization_configured",
    "administrator_configured",
    "preferences_configured",
)
PREFERENCES_CONFIGURATION_TYPE = "installation_preferences"
PREFERENCES_CONFIGURATION_KEY = "initial"


class InstallationState(StrEnum):
    UNCONFIGURED = "UNCONFIGURED"
    IN_PROGRESS = "IN_PROGRESS"
    READY_TO_COMPLETE = "READY_TO_COMPLETE"
    COMPLETED = "COMPLETED"


class InstallationSetupError(RuntimeError):
    def __init__(self, code: str, message: str, *, reason: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.reason = reason


@dataclass(frozen=True)
class OrganizationSetupCommand:
    name: str
    slug: str


@dataclass(frozen=True)
class AdministratorSetupCommand:
    email: str
    display_name: str | None
    password: str


@dataclass(frozen=True)
class PreferencesSetupCommand:
    language: str
    timezone: str


@dataclass(frozen=True)
class InstallationBootstrapCommand:
    organization_name: str
    organization_slug: str
    admin_email: str
    admin_display_name: str | None
    admin_password: str
    language: str
    timezone: str


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class InstallationSetupService:
    def __init__(
        self,
        platform_db: Session,
        identity_db: Session,
        settings: Settings,
        *,
        actor: str = "installation-setup",
    ) -> None:
        self.platform_db = platform_db
        self.identity_db = identity_db
        self.settings = settings
        self.actor = actor

    def _lock(self) -> None:
        self.platform_db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": SETUP_LOCK_KEY})

    def _current_setup(self) -> InstallationSetup | None:
        return self.platform_db.scalar(
            select(InstallationSetup).where(
                InstallationSetup.installation_instance_id == self.settings.installation_instance_id
            )
        )

    def _ensure_setup(self) -> InstallationSetup:
        self._lock()
        setup = self._current_setup()
        if setup is not None:
            if setup.setup_schema_version != SETUP_SCHEMA_VERSION:
                raise InstallationSetupError(
                    "INSTALLATION_EVIDENCE_INCONSISTENT",
                    "The persisted installation setup schema version is unsupported.",
                )
            return setup
        setup = InstallationSetup(
            installation_instance_id=self.settings.installation_instance_id,
            setup_schema_version=SETUP_SCHEMA_VERSION,
            created_by=self.actor,
            updated_by=self.actor,
        )
        self.platform_db.add(setup)
        self.platform_db.flush()
        self._audit(None, "installation_setup_started", "Installation setup started.", str(setup.installation_setup_id))
        return setup

    def _completion(self, setup: InstallationSetup) -> InstallationCompletionEvidence | None:
        return self.platform_db.scalar(
            select(InstallationCompletionEvidence).where(
                InstallationCompletionEvidence.installation_setup_id == setup.installation_setup_id
            )
        )

    def _assert_mutable(self, setup: InstallationSetup) -> None:
        if self._completion(setup) is not None:
            raise InstallationSetupError(
                "INSTALLATION_ALREADY_COMPLETED",
                "Installation setup has already been completed.",
            )

    def _evidence(self, setup: InstallationSetup) -> dict[str, InstallationSetupEvidence]:
        records = self.platform_db.scalars(
            select(InstallationSetupEvidence).where(
                InstallationSetupEvidence.installation_setup_id == setup.installation_setup_id
            )
        ).all()
        return {record.evidence_type: record for record in records}

    def _write_evidence(
        self,
        setup: InstallationSetup,
        *,
        evidence_type: str,
        organization_id: uuid.UUID | None,
        resource_type: str,
        resource_id: str,
        payload: dict,
    ) -> InstallationSetupEvidence:
        existing = self._evidence(setup).get(evidence_type)
        evidence_version = existing.evidence_version if existing is not None else 1
        evidence_hash = _canonical_hash(
            {
                "evidence_type": evidence_type,
                "evidence_version": evidence_version,
                "organization_id": str(organization_id) if organization_id else None,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "payload": payload,
            }
        )
        if existing is not None:
            if existing.evidence_hash == evidence_hash:
                return existing
            existing.organization_id = organization_id
            existing.resource_type = resource_type
            existing.resource_id = resource_id
            existing.evidence_payload = payload
            existing.evidence_hash = evidence_hash
            setup.updated_by = self.actor
            self.platform_db.add(existing)
            self.platform_db.add(setup)
            self.platform_db.flush()
            return existing
        record = InstallationSetupEvidence(
            installation_setup_id=setup.installation_setup_id,
            evidence_type=evidence_type,
            evidence_version=evidence_version,
            organization_id=organization_id,
            resource_type=resource_type,
            resource_id=resource_id,
            evidence_payload=payload,
            evidence_hash=evidence_hash,
            created_by=self.actor,
        )
        setup.updated_by = self.actor
        self.platform_db.add(record)
        self.platform_db.add(setup)
        self.platform_db.flush()
        return record

    def _audit(
        self,
        organization_id: uuid.UUID | None,
        event: str,
        summary: str,
        resource_id: str,
        metadata: dict | None = None,
    ) -> None:
        existing = self.platform_db.scalar(
            select(AuditEvent.id).where(
                AuditEvent.actor_type == "installation_setup",
                AuditEvent.resource_type == event,
                AuditEvent.resource_id == resource_id,
            )
        )
        if existing is None:
            self.platform_db.add(
                AuditEvent(
                    organization_id=organization_id,
                    actor_type="installation_setup",
                    actor_id=self.actor,
                    resource_type=event,
                    resource_id=resource_id,
                    summary=summary,
                    metadata_json=metadata or {},
                )
            )

    def status(self, *, include_details: bool = False) -> dict:
        setup = self._current_setup()
        if setup is None:
            return self._status_payload(None, {}, None, include_details=include_details)
        evidence = self._evidence(setup)
        return self._status_payload(setup, evidence, self._completion(setup), include_details=include_details)

    def persisted_evidence(self) -> dict[str, InstallationSetupEvidence]:
        setup = self._current_setup()
        if setup is None:
            return {}
        return self._evidence(setup)

    def _status_payload(
        self,
        setup: InstallationSetup | None,
        evidence: dict[str, InstallationSetupEvidence],
        completion: InstallationCompletionEvidence | None,
        *,
        include_details: bool,
    ) -> dict:
        completed_types = set(evidence)
        if completion is not None:
            state = InstallationState.COMPLETED
        elif not completed_types:
            state = InstallationState.UNCONFIGURED
        elif completed_types.issuperset(EVIDENCE_TYPES):
            state = InstallationState.READY_TO_COMPLETE
        else:
            state = InstallationState.IN_PROGRESS
        next_step = next((item for item in EVIDENCE_TYPES if item not in completed_types), None)
        if next_step is None and completion is None:
            next_step = "complete"
        details: dict[str, dict] = {}
        if include_details:
            for evidence_type, record in evidence.items():
                details[evidence_type] = dict(record.evidence_payload)
        return {
            "state": state.value,
            "token_authorized": False,
            "setup_available": completion is None,
            "setup_schema_version": setup.setup_schema_version if setup else SETUP_SCHEMA_VERSION,
            "steps": {evidence_type: evidence_type in completed_types for evidence_type in EVIDENCE_TYPES},
            "next_step": None if completion is not None else next_step,
            "ready_to_complete": state == InstallationState.READY_TO_COMPLETE,
            "details": details,
            "password_policy": {
                "min_length": self.settings.auth_password_min_length,
                "max_length": self.settings.auth_password_max_length,
                "block_context": self.settings.auth_password_block_context,
                "block_common": self.settings.auth_password_block_common,
            },
        }

    def configure_organization(self, command: OrganizationSetupCommand) -> dict:
        from app.identity.installation_bootstrap import (
            InstallationBootstrap,
            _get_or_create_organization,
            _normalize_inputs,
        )

        setup = self._ensure_setup()
        self._assert_mutable(setup)
        name, slug = _normalize_inputs(
            InstallationBootstrap(
                organization_name=command.name,
                organization_slug=command.slug,
                admin_email="unused@example.invalid",
                admin_display_name=None,
                admin_password="unused",
            )
        )
        existing_evidence = self._evidence(setup).get("organization_configured")
        if existing_evidence is not None and existing_evidence.evidence_payload != {"name": name, "slug": slug}:
            raise InstallationSetupError(
                "INSTALLATION_ORGANIZATION_INVALID",
                "The persisted installation organization conflicts with the requested organization.",
            )
        try:
            organization, _created = _get_or_create_organization(self.platform_db, name=name, slug=slug)
        except ValueError as exc:
            raise InstallationSetupError("INSTALLATION_ORGANIZATION_INVALID", str(exc)) from exc
        self._write_evidence(
            setup,
            evidence_type="organization_configured",
            organization_id=organization.id,
            resource_type="organization",
            resource_id=str(organization.id),
            payload={"name": organization.name, "slug": organization.slug},
        )
        self._audit(
            organization.id,
            "installation_organization_configured",
            "Installation organization configured.",
            str(setup.installation_setup_id),
        )
        self.platform_db.commit()
        return self.status(include_details=True)

    def configure_administrator(self, command: AdministratorSetupCommand) -> dict:
        from app.identity.installation_bootstrap import (
            _get_or_create_admin_role,
            _reconcile_admin_permissions,
        )

        setup = self._ensure_setup()
        self._assert_mutable(setup)
        evidence = self._evidence(setup)
        organization_evidence = evidence.get("organization_configured")
        if organization_evidence is None or organization_evidence.organization_id is None:
            raise InstallationSetupError(
                "INSTALLATION_SETUP_NOT_READY", "Configure the installation organization first."
            )
        organization = self.platform_db.get(Organization, organization_evidence.organization_id)
        if organization is None or organization.status != "active":
            raise InstallationSetupError(
                "INSTALLATION_EVIDENCE_INCONSISTENT", "The installation organization is unavailable."
            )
        role, _created = _get_or_create_admin_role(self.platform_db, organization)
        _reconcile_admin_permissions(self.platform_db, role)
        platform_role = reconcile_platform_owner_role(self.platform_db, actor=self.actor)
        self.platform_db.commit()
        try:
            result = bootstrap_initial_admin(
                self.identity_db,
                self.platform_db,
                self.settings,
                InitialAdminBootstrap(
                    email_display=command.email,
                    display_name=command.display_name,
                    password=command.password,
                    organization_id=organization.id,
                    role_id=role.id,
                ),
            )
        except PasswordPolicyError as exc:
            raise InstallationSetupError(
                "INSTALLATION_ADMINISTRATOR_INVALID",
                "The administrator password does not meet the configured password policy.",
                reason=exc.code,
            ) from exc
        except ValueError as exc:
            raise InstallationSetupError("INSTALLATION_ADMINISTRATOR_INVALID", str(exc)) from exc
        user = self.identity_db.get(IdentityUser, result.user_id)
        if user is None:
            raise InstallationSetupError(
                "INSTALLATION_EVIDENCE_INCONSISTENT", "The installation identity is unavailable."
            )
        self._lock()
        self._assert_mutable(setup)
        platform_assignment = reconcile_platform_owner_assignment(
            self.platform_db,
            role=platform_role,
            user_id=user.id,
            actor=self.actor,
        )
        self._write_evidence(
            setup,
            evidence_type="administrator_configured",
            organization_id=organization.id,
            resource_type="identity_user",
            resource_id=str(result.user_id),
            payload={
                "email": user.email_normalized,
                "display_name": user.display_name,
                "role_id": str(role.id),
                "role_code": role.code,
                "platform_role_id": str(platform_role.id),
                "platform_role_code": platform_role.code,
                "platform_assignment_id": str(platform_assignment.id),
            },
        )
        self._audit(
            None,
            "installation_platform_owner_assigned",
            "Initial platform owner role assigned.",
            str(setup.installation_setup_id),
            {
                "user_id": str(result.user_id),
                "role_id": str(platform_role.id),
                "role_code": platform_role.code,
                "assignment_id": str(platform_assignment.id),
            },
        )
        self._audit(
            organization.id,
            "installation_administrator_configured",
            "Installation administrator configured.",
            str(setup.installation_setup_id),
            {"user_id": str(result.user_id), "role_id": str(role.id)},
        )
        self.platform_db.commit()
        return self.status(include_details=True)

    def _configure_preferences_record(
        self, organization_id: uuid.UUID, command: PreferencesSetupCommand
    ) -> RuntimeConfigurationRevision:
        language = command.language.strip().lower()
        timezone = command.timezone.strip()
        if language not in {"en", "es"}:
            raise InstallationSetupError("INSTALLATION_PREFERENCES_INVALID", "Language is invalid.")
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError as exc:
            raise InstallationSetupError("INSTALLATION_PREFERENCES_INVALID", "Timezone is invalid.") from exc
        configuration = self.platform_db.scalar(
            select(RuntimeConfiguration).where(
                RuntimeConfiguration.organization_id == organization_id,
                RuntimeConfiguration.scope_type == "organization",
                RuntimeConfiguration.configuration_type == PREFERENCES_CONFIGURATION_TYPE,
                RuntimeConfiguration.configuration_key == PREFERENCES_CONFIGURATION_KEY,
            )
        )
        if configuration is None:
            configuration = RuntimeConfiguration(
                organization_id=organization_id,
                scope_type="organization",
                scope_key=None,
                configuration_type=PREFERENCES_CONFIGURATION_TYPE,
                configuration_key=PREFERENCES_CONFIGURATION_KEY,
                created_by=self.actor,
                updated_by=self.actor,
            )
            self.platform_db.add(configuration)
            self.platform_db.flush()
        payload = {"language": language, "timezone": timezone}
        active = self.platform_db.scalar(
            select(RuntimeConfigurationRevision).where(
                RuntimeConfigurationRevision.configuration_id == configuration.id,
                RuntimeConfigurationRevision.status == "active",
            )
        )
        if active is not None and active.payload == payload:
            return active
        if active is not None:
            active.status = "superseded"
            self.platform_db.add(active)
            self.platform_db.flush()
        revision_number = (
            int(
                self.platform_db.scalar(
                    select(func.coalesce(func.max(RuntimeConfigurationRevision.revision), 0)).where(
                        RuntimeConfigurationRevision.configuration_id == configuration.id
                    )
                )
                or 0
            )
            + 1
        )
        revision = RuntimeConfigurationRevision(
            configuration_id=configuration.id,
            organization_id=organization_id,
            schema_version=1,
            revision=revision_number,
            status="active",
            payload=payload,
            created_by=self.actor,
            updated_by=self.actor,
        )
        self.platform_db.add(revision)
        self.platform_db.flush()
        return revision

    def configure_preferences(self, command: PreferencesSetupCommand) -> dict:
        setup = self._ensure_setup()
        self._assert_mutable(setup)
        evidence = self._evidence(setup)
        organization_evidence = evidence.get("organization_configured")
        if organization_evidence is None or organization_evidence.organization_id is None:
            raise InstallationSetupError(
                "INSTALLATION_SETUP_NOT_READY", "Configure the installation organization first."
            )
        if evidence.get("administrator_configured") is None:
            raise InstallationSetupError(
                "INSTALLATION_SETUP_NOT_READY", "Configure the installation administrator first."
            )
        revision = self._configure_preferences_record(organization_evidence.organization_id, command)
        self._write_evidence(
            setup,
            evidence_type="preferences_configured",
            organization_id=organization_evidence.organization_id,
            resource_type="runtime_configuration_revision",
            resource_id=str(revision.id),
            payload=dict(revision.payload),
        )
        self._audit(
            organization_evidence.organization_id,
            "installation_preferences_configured",
            "Installation preferences configured.",
            str(setup.installation_setup_id),
            {"configuration_revision_id": str(revision.id)},
        )
        self.platform_db.commit()
        return self.status(include_details=True)

    def _verified_resources(
        self,
        setup: InstallationSetup,
        evidence: dict[str, InstallationSetupEvidence],
        *,
        require_platform_authority: bool = True,
    ) -> tuple[Organization, IdentityUser, Role]:
        if not set(EVIDENCE_TYPES).issubset(evidence):
            raise InstallationSetupError(
                "INSTALLATION_SETUP_NOT_READY", "All installation setup steps must be completed first."
            )
        organization_evidence = evidence["organization_configured"]
        administrator_evidence = evidence["administrator_configured"]
        preferences_evidence = evidence["preferences_configured"]
        if organization_evidence.organization_id is None:
            raise InstallationSetupError("INSTALLATION_EVIDENCE_INCONSISTENT", "Organization evidence is incomplete.")
        try:
            user_id = uuid.UUID(administrator_evidence.resource_id)
            role_id = uuid.UUID(str(administrator_evidence.evidence_payload.get("role_id")))
            preference_revision_id = uuid.UUID(preferences_evidence.resource_id)
            platform_role_id = (
                uuid.UUID(str(administrator_evidence.evidence_payload.get("platform_role_id")))
                if require_platform_authority
                else None
            )
            platform_assignment_id = (
                uuid.UUID(str(administrator_evidence.evidence_payload.get("platform_assignment_id")))
                if require_platform_authority
                else None
            )
        except (TypeError, ValueError) as exc:
            raise InstallationSetupError(
                "INSTALLATION_EVIDENCE_INCONSISTENT", "Persisted installation evidence is invalid."
            ) from exc
        organization = self.platform_db.get(Organization, organization_evidence.organization_id)
        user = self.identity_db.get(IdentityUser, user_id)
        role = self.platform_db.get(Role, role_id)
        platform_role = self.platform_db.get(Role, platform_role_id) if platform_role_id else None
        platform_assignment = (
            self.platform_db.get(RoleAssignment, platform_assignment_id) if platform_assignment_id else None
        )
        if user is None:
            raise InstallationSetupError(
                "INSTALLATION_EVIDENCE_INCONSISTENT", "The installation identity is unavailable."
            )
        membership = self.identity_db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == user.id,
                OrganizationMembership.organization_id == organization_evidence.organization_id,
                OrganizationMembership.role_id == role_id,
                OrganizationMembership.status == "active",
            )
        )
        assignment = self.platform_db.scalar(
            select(RoleAssignment).where(
                RoleAssignment.organization_id == organization_evidence.organization_id,
                RoleAssignment.role_id == role_id,
                RoleAssignment.principal_type == "user",
                RoleAssignment.principal_id == administrator_evidence.resource_id,
                RoleAssignment.scope_type == "organization",
                RoleAssignment.scope_id == str(organization_evidence.organization_id),
                RoleAssignment.status == "active",
            )
        )
        platform_permissions = (
            {
                (resource, action)
                for resource, action in self.platform_db.execute(
                    select(Permission.resource, Permission.action)
                    .join(RolePermission, RolePermission.permission_id == Permission.id)
                    .where(RolePermission.role_id == platform_role_id)
                ).all()
            }
            if platform_role_id
            else set()
        )
        required_platform_permissions = {
            (resource, action) for resource, action, _description in PLATFORM_ADMIN_PERMISSION_CATALOG
        }
        preference_revision = self.platform_db.get(RuntimeConfigurationRevision, preference_revision_id)
        preference_configuration = (
            self.platform_db.get(RuntimeConfiguration, preference_revision.configuration_id)
            if preference_revision is not None
            else None
        )
        consistent = (
            organization is not None
            and organization.status == "active"
            and organization_evidence.resource_type == "organization"
            and organization_evidence.resource_id == str(organization.id)
            and organization_evidence.evidence_payload.get("name") == organization.name
            and organization_evidence.evidence_payload.get("slug") == organization.slug
            and user is not None
            and user.status == "active"
            and administrator_evidence.resource_type == "identity_user"
            and administrator_evidence.organization_id == organization.id
            and administrator_evidence.evidence_payload.get("email") == user.email_normalized
            and administrator_evidence.evidence_payload.get("display_name") == user.display_name
            and role is not None
            and role.status == "active"
            and role.organization_id == organization.id
            and administrator_evidence.evidence_payload.get("role_code") == role.code
            and membership is not None
            and assignment is not None
            and (
                not require_platform_authority
                or (
                    platform_role is not None
                    and platform_role.organization_id is None
                    and platform_role.code == PLATFORM_OWNER_ROLE_CODE
                    and platform_role.status == "active"
                    and platform_role.is_system is False
                    and isinstance(platform_role.config, dict)
                    and platform_role.config.get("scope") == "platform"
                    and administrator_evidence.evidence_payload.get("platform_role_code") == PLATFORM_OWNER_ROLE_CODE
                    and platform_assignment is not None
                    and platform_assignment.organization_id is None
                    and platform_assignment.role_id == platform_role_id
                    and platform_assignment.principal_type == "user"
                    and platform_assignment.principal_id == str(user.id)
                    and platform_assignment.scope_type == "platform"
                    and platform_assignment.scope_id == "platform"
                    and platform_assignment.status == "active"
                    and required_platform_permissions.issubset(platform_permissions)
                )
            )
            and preference_revision is not None
            and preference_revision.status == "active"
            and preferences_evidence.resource_type == "runtime_configuration_revision"
            and preference_revision.organization_id == organization.id
            and preferences_evidence.organization_id == organization.id
            and preference_configuration is not None
            and preference_configuration.organization_id == organization.id
            and preference_configuration.scope_type == "organization"
            and preference_configuration.scope_key is None
            and preference_configuration.configuration_type == PREFERENCES_CONFIGURATION_TYPE
            and preference_configuration.configuration_key == PREFERENCES_CONFIGURATION_KEY
            and preference_revision.payload
            == {
                "language": preferences_evidence.evidence_payload.get("language"),
                "timezone": preferences_evidence.evidence_payload.get("timezone"),
            }
        )
        if not consistent:
            raise InstallationSetupError(
                "INSTALLATION_EVIDENCE_INCONSISTENT",
                "Persisted installation evidence does not match authoritative resources.",
            )
        return organization, user, role

    def complete(self, *, origin: str = "setup_wizard") -> dict:
        setup = self._ensure_setup()
        self._lock()
        existing = self._completion(setup)
        if existing is not None:
            return self.status(include_details=True)
        evidence = self._evidence(setup)
        organization, user, role = self._verified_resources(
            setup,
            evidence,
            require_platform_authority=origin != "legacy_bootstrap_reconciliation",
        )
        digest = _canonical_hash(
            {
                "setup_schema_version": setup.setup_schema_version,
                "evidence": [
                    {"type": evidence_type, "hash": evidence[evidence_type].evidence_hash}
                    for evidence_type in EVIDENCE_TYPES
                ],
            }
        )
        completion = InstallationCompletionEvidence(
            installation_setup_id=setup.installation_setup_id,
            organization_id=organization.id,
            initial_identity_user_id=user.id,
            initial_role_id=role.id,
            setup_schema_version=setup.setup_schema_version,
            evidence_digest=digest,
            completion_metadata={"origin": origin, "evidence_types": list(EVIDENCE_TYPES)},
            completed_by=self.actor,
        )
        setup.updated_by = self.actor
        self.platform_db.add(completion)
        self.platform_db.add(setup)
        self._audit(
            organization.id,
            "installation_setup_completed",
            "Installation setup completed from authoritative evidence.",
            str(setup.installation_setup_id),
            {"evidence_digest": digest, "origin": origin},
        )
        self.platform_db.commit()
        return self.status(include_details=True)

    def reconcile_completed_platform_owner(self) -> dict[str, str]:
        self._lock()
        setup = self._current_setup()
        if setup is None:
            raise InstallationSetupError(
                "INSTALLATION_EVIDENCE_INCONSISTENT",
                "Persisted installation setup evidence is unavailable.",
            )
        completion = self._completion(setup)
        if completion is None:
            raise InstallationSetupError(
                "INSTALLATION_SETUP_NOT_COMPLETED",
                "Platform owner reconciliation requires a completed installation.",
            )
        evidence = self._evidence(setup)
        if not set(EVIDENCE_TYPES).issubset(evidence):
            raise InstallationSetupError(
                "INSTALLATION_EVIDENCE_INCONSISTENT",
                "Completed installation evidence is incomplete.",
            )
        administrator_evidence = evidence.get("administrator_configured")
        if administrator_evidence is None:
            raise InstallationSetupError(
                "INSTALLATION_EVIDENCE_INCONSISTENT",
                "Persisted administrator evidence is unavailable.",
            )
        try:
            user_id = uuid.UUID(administrator_evidence.resource_id)
            organization_role_id = uuid.UUID(str(administrator_evidence.evidence_payload.get("role_id")))
        except (TypeError, ValueError) as exc:
            raise InstallationSetupError(
                "INSTALLATION_EVIDENCE_INCONSISTENT",
                "Persisted administrator evidence is invalid.",
            ) from exc
        user = self.identity_db.get(IdentityUser, user_id)
        organization_role = self.platform_db.get(Role, organization_role_id)
        organization = (
            self.platform_db.get(Organization, administrator_evidence.organization_id)
            if administrator_evidence.organization_id
            else None
        )
        membership = self.identity_db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == user_id,
                OrganizationMembership.organization_id == administrator_evidence.organization_id,
                OrganizationMembership.role_id == organization_role_id,
                OrganizationMembership.status == "active",
            )
        )
        organization_assignment = self.platform_db.scalar(
            select(RoleAssignment).where(
                RoleAssignment.organization_id == administrator_evidence.organization_id,
                RoleAssignment.role_id == organization_role_id,
                RoleAssignment.principal_type == "user",
                RoleAssignment.principal_id == str(user_id),
                RoleAssignment.scope_type == "organization",
                RoleAssignment.scope_id == str(administrator_evidence.organization_id),
                RoleAssignment.status == "active",
            )
        )
        evidence_is_consistent = (
            administrator_evidence.resource_type == "identity_user"
            and administrator_evidence.organization_id is not None
            and completion.initial_identity_user_id == user_id
            and completion.organization_id == administrator_evidence.organization_id
            and completion.initial_role_id == organization_role_id
            and user is not None
            and user.status == "active"
            and administrator_evidence.evidence_payload.get("email") == user.email_normalized
            and administrator_evidence.evidence_payload.get("display_name") == user.display_name
            and organization is not None
            and organization.status == "active"
            and organization_role is not None
            and organization_role.organization_id == organization.id
            and organization_role.status == "active"
            and administrator_evidence.evidence_payload.get("role_code") == organization_role.code
            and membership is not None
            and organization_assignment is not None
        )
        if not evidence_is_consistent:
            raise InstallationSetupError(
                "INSTALLATION_EVIDENCE_INCONSISTENT",
                "Persisted administrator evidence does not match authoritative resources.",
            )

        platform_fields = {
            "platform_role_id": administrator_evidence.evidence_payload.get("platform_role_id"),
            "platform_role_code": administrator_evidence.evidence_payload.get("platform_role_code"),
            "platform_assignment_id": administrator_evidence.evidence_payload.get("platform_assignment_id"),
        }
        populated_platform_fields = sum(value is not None for value in platform_fields.values())
        if populated_platform_fields not in {0, len(platform_fields)}:
            raise InstallationSetupError(
                "INSTALLATION_EVIDENCE_INCONSISTENT",
                "Persisted platform owner evidence is incomplete.",
            )

        platform_role = reconcile_platform_owner_role(self.platform_db, actor=self.actor)
        platform_assignment = reconcile_platform_owner_assignment(
            self.platform_db,
            role=platform_role,
            user_id=user_id,
            actor=self.actor,
        )
        if populated_platform_fields and platform_fields != {
            "platform_role_id": str(platform_role.id),
            "platform_role_code": platform_role.code,
            "platform_assignment_id": str(platform_assignment.id),
        }:
            raise InstallationSetupError(
                "INSTALLATION_EVIDENCE_INCONSISTENT",
                "Persisted platform owner evidence conflicts with authoritative resources.",
            )

        self._write_evidence(
            setup,
            evidence_type=administrator_evidence.evidence_type,
            organization_id=administrator_evidence.organization_id,
            resource_type=administrator_evidence.resource_type,
            resource_id=administrator_evidence.resource_id,
            payload={
                **administrator_evidence.evidence_payload,
                "platform_role_id": str(platform_role.id),
                "platform_role_code": platform_role.code,
                "platform_assignment_id": str(platform_assignment.id),
            },
        )
        reconciled_evidence = self._evidence(setup)
        completion.evidence_digest = _canonical_hash(
            {
                "setup_schema_version": setup.setup_schema_version,
                "evidence": [
                    {"type": evidence_type, "hash": reconciled_evidence[evidence_type].evidence_hash}
                    for evidence_type in EVIDENCE_TYPES
                ],
            }
        )
        self.platform_db.add(completion)
        self._audit(
            None,
            "installation_platform_owner_reconciled",
            "Completed installation platform owner authority reconciled.",
            str(setup.installation_setup_id),
            {
                "user_id": str(user_id),
                "role_id": str(platform_role.id),
                "role_code": platform_role.code,
                "assignment_id": str(platform_assignment.id),
            },
        )
        self.platform_db.commit()
        return {
            "installation_setup_id": str(setup.installation_setup_id),
            "user_id": str(user_id),
            "platform_role_id": str(platform_role.id),
            "platform_assignment_id": str(platform_assignment.id),
            "state": InstallationState.COMPLETED.value,
        }

    def bootstrap(self, command: InstallationBootstrapCommand) -> dict:
        self.configure_organization(
            OrganizationSetupCommand(name=command.organization_name, slug=command.organization_slug)
        )
        self.configure_administrator(
            AdministratorSetupCommand(
                email=command.admin_email,
                display_name=command.admin_display_name,
                password=command.admin_password,
            )
        )
        self.configure_preferences(PreferencesSetupCommand(language=command.language, timezone=command.timezone))
        return self.complete(origin="bootstrap_cli")

    def reconcile_legacy_bootstrap(self) -> bool:
        if self._current_setup() is not None:
            return False
        organizations = self.platform_db.scalars(select(Organization).where(Organization.status == "active")).all()
        candidates = [item for item in organizations if (item.config or {}).get("installation_bootstrap") is True]
        if len(candidates) != 1:
            return False
        organization = candidates[0]
        roles = self.platform_db.scalars(
            select(Role).where(Role.organization_id == organization.id, Role.status == "active")
        ).all()
        role_candidates = [item for item in roles if (item.config or {}).get("installation_bootstrap") is True]
        users = self.identity_db.scalars(select(IdentityUser).where(IdentityUser.status == "active")).all()
        if len(role_candidates) != 1 or len(users) != 1:
            return False
        role = role_candidates[0]
        user = users[0]
        membership = self.identity_db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.user_id == user.id,
                OrganizationMembership.organization_id == organization.id,
                OrganizationMembership.role_id == role.id,
                OrganizationMembership.status == "active",
            )
        )
        assignment = self.platform_db.scalar(
            select(RoleAssignment).where(
                RoleAssignment.organization_id == organization.id,
                RoleAssignment.role_id == role.id,
                RoleAssignment.principal_type == "user",
                RoleAssignment.principal_id == str(user.id),
                RoleAssignment.scope_type == "organization",
                RoleAssignment.scope_id == str(organization.id),
                RoleAssignment.status == "active",
            )
        )
        bootstrap_audit = self.platform_db.scalar(
            select(AuditEvent.id).where(
                AuditEvent.organization_id == organization.id,
                AuditEvent.actor_type == "installation_bootstrap",
                AuditEvent.resource_type == "installation_bootstrap",
            )
        )
        if membership is None or assignment is None or bootstrap_audit is None:
            return False
        language = self.settings.installation_default_language.strip().lower()
        timezone = self.settings.installation_default_timezone.strip()
        if language not in {"en", "es"}:
            return False
        try:
            ZoneInfo(timezone)
        except ZoneInfoNotFoundError:
            return False
        setup = self._ensure_setup()
        origin = {"origin": "legacy_bootstrap_reconciliation"}
        self._write_evidence(
            setup,
            evidence_type="organization_configured",
            organization_id=organization.id,
            resource_type="organization",
            resource_id=str(organization.id),
            payload={"name": organization.name, "slug": organization.slug, **origin},
        )
        self._write_evidence(
            setup,
            evidence_type="administrator_configured",
            organization_id=organization.id,
            resource_type="identity_user",
            resource_id=str(user.id),
            payload={
                "email": user.email_normalized,
                "display_name": user.display_name,
                "role_id": str(role.id),
                "role_code": role.code,
                **origin,
            },
        )
        revision = self._configure_preferences_record(
            organization.id,
            PreferencesSetupCommand(
                language=language,
                timezone=timezone,
            ),
        )
        self._write_evidence(
            setup,
            evidence_type="preferences_configured",
            organization_id=organization.id,
            resource_type="runtime_configuration_revision",
            resource_id=str(revision.id),
            payload={**revision.payload, **origin},
        )
        self.platform_db.commit()
        self.complete(origin="legacy_bootstrap_reconciliation")
        return True
