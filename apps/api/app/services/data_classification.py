from __future__ import annotations

from typing import Any, Iterable, TypeVar

DATA_CLASSIFICATIONS = {"operational", "reference", "validation", "legacy"}
T = TypeVar("T")


def _explicit_classification(payload: dict[str, Any]) -> str | None:
    for key in ("data_classification", "data_origin", "origin"):
        value = str(payload.get(key) or "").strip().lower()
        if value in DATA_CLASSIFICATIONS:
            return value
    return None


def classify_persisted_metadata(*values: Any, default: str = "operational") -> str:
    """Classify persisted data without using labels, names or transient state."""
    classifications: list[str] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        explicit = _explicit_classification(value)
        if explicit:
            classifications.append(explicit)
        if (
            value.get("validation_generated") is True
            or bool(value.get("smoke"))
            or bool(value.get("smoke_runtime"))
            or bool(value.get("execution_key"))
            or value.get("scenario") == "local_product_acceptance"
        ):
            classifications.append("validation")
        if value.get("reference_tenant") is True or value.get("canonical_product_reference") is True:
            classifications.append("reference")
        if value.get("legacy") is True or value.get("legacy_unscoped") is True:
            classifications.append("legacy")
        for nested in value.values():
            if isinstance(nested, dict):
                nested_classification = classify_persisted_metadata(nested, default=default)
                if nested_classification != default:
                    classifications.append(nested_classification)
            elif isinstance(nested, list):
                for item in nested:
                    if isinstance(item, dict):
                        nested_classification = classify_persisted_metadata(item, default=default)
                        if nested_classification != default:
                            classifications.append(nested_classification)
    for classification in ("legacy", "validation", "reference", "operational"):
        if classification in classifications:
            return classification
    return default if default in DATA_CLASSIFICATIONS else "operational"


def is_visible_product_data(*values: Any, include_validation: bool = False) -> bool:
    classification = classify_persisted_metadata(*values)
    if classification == "legacy":
        return False
    return include_validation or classification != "validation"


def filter_visible_product_data(
    records: Iterable[T],
    metadata_getter: Any,
    *,
    include_validation: bool = False,
) -> list[T]:
    return [
        record
        for record in records
        if is_visible_product_data(*metadata_getter(record), include_validation=include_validation)
    ]
