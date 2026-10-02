import pytest

from app.services.operation_catalog import build_default_operation_catalog, validate_artifact_publication_reconciliation


def test_default_catalog_contains_reconciliation_contract() -> None:
    contract = build_default_operation_catalog().get("artifact_publication_reconciliation")
    assert contract.permission == "control_plane.reconciliation.run"
    assert contract.preview_supported is True


def test_reconciliation_defaults_are_stable() -> None:
    values = validate_artifact_publication_reconciliation({})
    assert values["limit"] == 100
    assert values["statuses"] is None
    assert values["cursor"] is None
    assert values["dry_run"] is False


def test_unknown_parameter_is_rejected() -> None:
    with pytest.raises(ValueError):
        validate_artifact_publication_reconciliation({"extra": "value"})


def test_boolean_limit_is_rejected() -> None:
    with pytest.raises(ValueError):
        validate_artifact_publication_reconciliation({"limit": True})


def test_statuses_must_be_a_list() -> None:
    with pytest.raises(ValueError):
        validate_artifact_publication_reconciliation({"statuses": "published"})
