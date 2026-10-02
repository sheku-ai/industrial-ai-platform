from __future__ import annotations

from dataclasses import dataclass

from app.identity.models import AuthSession, IdentityUser, OrganizationMembership


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    user: IdentityUser
    session: AuthSession
    memberships: tuple[OrganizationMembership, ...]

    @property
    def actor_reference(self) -> str:
        return str(self.user.id)

    @property
    def organization_ids(self) -> frozenset:
        return frozenset(item.organization_id for item in self.memberships if item.status == "active")
