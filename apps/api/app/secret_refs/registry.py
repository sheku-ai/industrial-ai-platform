from __future__ import annotations

from app.secret_refs.base import SecretResolver
from app.secret_refs.disabled import DisabledSecretResolver


class SecretResolverRegistry:
    def __init__(self, disabled_resolver: SecretResolver | None = None) -> None:
        self._disabled_resolver = disabled_resolver or DisabledSecretResolver()
        self._resolvers: dict[str, SecretResolver] = {
            self._disabled_resolver.resolver_type: self._disabled_resolver,
        }

    def register(self, resolver: SecretResolver, *, replace: bool = False) -> None:
        resolver_type = resolver.resolver_type.strip()
        if not resolver_type:
            raise ValueError("resolver_type must not be empty")
        if resolver_type in self._resolvers and not replace:
            raise ValueError(f"resolver already registered: {resolver_type}")
        self._resolvers[resolver_type] = resolver

    def resolve(self, resolver_type: str | None) -> SecretResolver:
        if not resolver_type:
            return self._disabled_resolver
        return self._resolvers.get(resolver_type.strip(), self._disabled_resolver)

    def registered_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._resolvers))
