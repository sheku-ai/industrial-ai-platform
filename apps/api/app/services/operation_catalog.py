from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OperationContract:
    name: str
    validator: Callable[[dict[str, Any]], dict[str, Any]]
    permission: str
    preview_supported: bool


class OperationCatalog:
    def __init__(self) -> None:
        self._contracts: dict[str, OperationContract] = {}

    def add(self, contract: OperationContract) -> None:
        key = contract.name.strip()
        if not key or key in self._contracts:
            raise ValueError("invalid operation contract")
        self._contracts[key] = contract

    def get(self, name: str) -> OperationContract:
        contract = self._contracts.get(name)
        if contract is None:
            raise LookupError("operation contract was not found")
        return contract

    def all(self) -> tuple[OperationContract, ...]:
        return tuple(self._contracts[key] for key in sorted(self._contracts))


def validate_artifact_publication_reconciliation(
    values: dict[str, Any],
) -> dict[str, Any]:
    allowed = {"limit", "statuses", "cursor", "dry_run"}
    if set(values) - allowed:
        raise ValueError("unsupported reconciliation parameter")

    limit = values.get("limit", 100)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100")

    statuses = values.get("statuses")
    if statuses is not None and (not isinstance(statuses, list) or not all(isinstance(item, str) for item in statuses)):
        raise ValueError("statuses must be a list of strings")

    cursor = values.get("cursor")
    if cursor is not None and not isinstance(cursor, str):
        raise ValueError("cursor must be a string")

    dry_run = values.get("dry_run", False)
    if not isinstance(dry_run, bool):
        raise ValueError("dry_run must be boolean")

    return {
        "limit": limit,
        "statuses": statuses,
        "cursor": cursor,
        "dry_run": dry_run,
    }


def build_default_operation_catalog() -> OperationCatalog:
    catalog = OperationCatalog()
    catalog.add(
        OperationContract(
            name="artifact_publication_reconciliation",
            validator=validate_artifact_publication_reconciliation,
            permission="control_plane.reconciliation.run",
            preview_supported=True,
        )
    )
    return catalog
