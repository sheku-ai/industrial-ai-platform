from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "main.py"
GUARD = ROOT / "app" / "services" / "schema_compatibility.py"


def test_api_registers_database_schema_startup_guard() -> None:
    source = MAIN.read_text(encoding="utf-8")

    assert 'from app.services.schema_compatibility import assert_database_schema_compatible' in source
    assert "lifespan=lifespan" in source
    assert "validate_database_schema(application)" in source
    assert 'assert_database_schema_compatible(settings.database_url)' in source


def test_api_lifespan_runs_startup_validation_once_for_same_application(monkeypatch) -> None:
    import main as module

    validated_applications = []
    monkeypatch.setattr(module, "validate_database_schema", validated_applications.append)
    application = FastAPI(lifespan=module.lifespan)

    with TestClient(application):
        assert validated_applications == [application]

    assert validated_applications == [application]


def test_api_tree_has_no_legacy_lifecycle_registration() -> None:
    legacy_registration = "." + "on_" + "event("

    for path in ROOT.rglob("*.py"):
        assert legacy_registration not in path.read_text(encoding="utf-8")


def test_schema_guard_rejects_non_compatible_report(monkeypatch) -> None:
    import app.services.schema_compatibility as module

    class FakeScript:
        def get_heads(self):
            return ["head_b"]

        def walk_revisions(self):
            return [type("Revision", (), {"revision": "head_b"})()]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    class FakeEngine:
        def connect(self):
            return FakeConnection()

        def dispose(self):
            return None

    class FakeContext:
        def get_current_heads(self):
            return ("unknown_revision",)

    monkeypatch.setattr(module.ScriptDirectory, "from_config", lambda _config: FakeScript())
    monkeypatch.setattr(module, "create_engine", lambda *_args, **_kwargs: FakeEngine())
    monkeypatch.setattr(module.MigrationContext, "configure", lambda _connection: FakeContext())

    with pytest.raises(RuntimeError, match="unknown_database_revision"):
        module.assert_database_schema_compatible("postgresql+psycopg://host/database")
