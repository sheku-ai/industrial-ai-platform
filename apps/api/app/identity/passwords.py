from __future__ import annotations

from dataclasses import dataclass
import unicodedata

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import Settings


class PasswordPolicyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PasswordContext:
    email: str | None = None
    display_name: str | None = None
    organization_name: str | None = None
    organization_slug: str | None = None


COMMON_PASSWORD_BLOCKLIST_V1 = frozenset(
    {
        "123456789",
        "admin123456",
        "administrator",
        "administrator123",
        "changeme",
        "changemechangeme",
        "letmein",
        "password",
        "password123",
        "passwordpassword",
        "qwerty",
        "welcome",
        "welcome123456789",
    }
)


def _comparison_value(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _context_fragments(value: str) -> tuple[str, ...]:
    fragments: list[str] = []
    current: list[str] = []
    for character in unicodedata.normalize("NFKC", value):
        if character.isalnum():
            current.append(character)
        elif current:
            fragments.append("".join(current))
            current = []
    if current:
        fragments.append("".join(current))
    return (value, *fragments)


def _context_values(context: PasswordContext | None) -> tuple[str, ...]:
    values = ["SHEKU"]
    if context is None:
        return tuple(values)
    if context.email:
        values.append(context.email)
        local_part, separator, _domain = context.email.partition("@")
        if separator:
            values.extend(_context_fragments(local_part))
    for value in (
        context.display_name,
        context.organization_name,
        context.organization_slug,
    ):
        if value:
            values.extend(_context_fragments(value))
    return tuple(values)


@dataclass(frozen=True)
class PasswordVerification:
    valid: bool
    needs_rehash: bool = False


class PasswordManager:
    algorithm = "argon2id"
    parameter_version = 1

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._hasher = PasswordHasher(
            time_cost=settings.auth_argon2_time_cost,
            memory_cost=settings.auth_argon2_memory_cost_kib,
            parallelism=settings.auth_argon2_parallelism,
            hash_len=settings.auth_argon2_hash_length,
            salt_len=settings.auth_argon2_salt_length,
            type=Type.ID,
        )
        self._dummy_hash = self._hasher.hash("identity-timing-equalization-value")

    @property
    def parameters(self) -> dict[str, int | str]:
        return {
            "version": self.parameter_version,
            "type": "argon2id",
            "time_cost": self.settings.auth_argon2_time_cost,
            "memory_cost_kib": self.settings.auth_argon2_memory_cost_kib,
            "parallelism": self.settings.auth_argon2_parallelism,
            "hash_length": self.settings.auth_argon2_hash_length,
            "salt_length": self.settings.auth_argon2_salt_length,
        }

    def validate_password(
        self,
        password: str,
        *,
        context: PasswordContext | None = None,
    ) -> None:
        length = len(password)
        if length < self.settings.auth_password_min_length:
            raise PasswordPolicyError(
                "PASSWORD_TOO_SHORT",
                f"password must contain at least {self.settings.auth_password_min_length} characters",
            )
        if length > self.settings.auth_password_max_length:
            raise PasswordPolicyError(
                "PASSWORD_TOO_LONG",
                f"password must contain at most {self.settings.auth_password_max_length} characters",
            )
        comparison = _comparison_value(password)
        if self.settings.auth_password_block_common and comparison in COMMON_PASSWORD_BLOCKLIST_V1:
            raise PasswordPolicyError(
                "PASSWORD_COMMON",
                "password is present in the local common-password blocklist",
            )
        if self.settings.auth_password_block_context:
            normalized_context = (_comparison_value(value) for value in _context_values(context))
            context_values = {value for value in normalized_context if len(value) >= 4}
            if any(value in comparison for value in context_values):
                raise PasswordPolicyError(
                    "PASSWORD_CONTEXT_MATCH",
                    "password is too similar to identifiable account or organization context",
                )

    def hash_password(
        self,
        password: str,
        *,
        context: PasswordContext | None = None,
    ) -> str:
        self.validate_password(password, context=context)
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> PasswordVerification:
        try:
            valid = self._hasher.verify(password_hash, password)
        except (InvalidHashError, VerificationError, VerifyMismatchError):
            return PasswordVerification(valid=False)
        return PasswordVerification(
            valid=bool(valid),
            needs_rehash=bool(valid and self._hasher.check_needs_rehash(password_hash)),
        )

    def equalize_unknown_user(self, password: str) -> None:
        self.verify(self._dummy_hash, password)
