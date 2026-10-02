from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

MigrationCompatibility = Literal[
    "compatible",
    "pending",
    "unversioned",
    "multiple_repository_heads",
    "multiple_database_heads",
    "unknown_database_revision",
    "database_ahead_or_diverged",
]


@dataclass(frozen=True)
class MigrationSafetyReport:
    compatibility: MigrationCompatibility
    repository_heads: tuple[str, ...]
    database_heads: tuple[str, ...]
    pending_revisions: tuple[str, ...] = ()
    detail: str | None = None

    @property
    def startup_compatible(self) -> bool:
        return self.compatibility == "compatible"

    @property
    def migration_required(self) -> bool:
        return self.compatibility in {"pending", "unversioned"}


def evaluate_migration_safety(
    *,
    repository_heads: Iterable[str],
    database_heads: Iterable[str],
    known_revisions: Iterable[str],
    pending_revisions: Iterable[str] = (),
) -> MigrationSafetyReport:
    repo = tuple(sorted(set(repository_heads)))
    database = tuple(sorted(set(database_heads)))
    known = set(known_revisions)
    pending = tuple(pending_revisions)

    if len(repo) != 1:
        return MigrationSafetyReport(
            compatibility="multiple_repository_heads",
            repository_heads=repo,
            database_heads=database,
            detail=f"expected exactly one repository head, found {len(repo)}",
        )

    if len(database) > 1:
        return MigrationSafetyReport(
            compatibility="multiple_database_heads",
            repository_heads=repo,
            database_heads=database,
            detail=f"expected at most one database head, found {len(database)}",
        )

    if not database:
        return MigrationSafetyReport(
            compatibility="unversioned",
            repository_heads=repo,
            database_heads=database,
            pending_revisions=pending,
            detail="database has no Alembic revision",
        )

    current = database[0]
    if current not in known:
        return MigrationSafetyReport(
            compatibility="unknown_database_revision",
            repository_heads=repo,
            database_heads=database,
            detail=f"database revision is not present in this repository: {current}",
        )

    if current == repo[0]:
        return MigrationSafetyReport(
            compatibility="compatible",
            repository_heads=repo,
            database_heads=database,
        )

    if pending:
        return MigrationSafetyReport(
            compatibility="pending",
            repository_heads=repo,
            database_heads=database,
            pending_revisions=pending,
            detail=f"database requires {len(pending)} forward migration(s)",
        )

    return MigrationSafetyReport(
        compatibility="database_ahead_or_diverged",
        repository_heads=repo,
        database_heads=database,
        detail="database revision is not an ancestor of the repository head",
    )
