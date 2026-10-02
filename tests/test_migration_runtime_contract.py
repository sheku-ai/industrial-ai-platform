from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
GUARD = ROOT / "apps" / "api" / "migration_guard.py"


def test_compose_uses_guarded_forward_only_migrator() -> None:
    source = COMPOSE.read_text(encoding="utf-8")

    assert 'command: ["python", "migration_guard.py", "apply"]' in source
    assert "condition: service_completed_successfully" in source
    assert '"8000:8000"' in source
    assert '"3000:3000"' in source
    assert "${API_PORT" not in source
    assert "${PORTAL_PORT" not in source


def test_migration_guard_never_invokes_downgrade_or_stamp() -> None:
    source = GUARD.read_text(encoding="utf-8")

    assert 'command.upgrade(config, "head")' in source
    assert "command.downgrade" not in source
    assert "command.stamp" not in source
    assert 'choices=("check", "apply")' in source


def test_migration_guard_reports_duration_and_final_compatibility() -> None:
    source = GUARD.read_text(encoding="utf-8")

    assert "duration_seconds" in source
    assert "after = migration_report(config)" in source
    assert "return 0 if after.startup_compatible else 1" in source


def test_migration_guard_never_uses_alembic_placeholder_database() -> None:
    source = GUARD.read_text(encoding="utf-8")
    expected_local_url = (
        'LOCAL_DATABASE_URL = "postgresql+psycopg://industrial_ai:industrial_ai@127.0.0.1:5432/industrial_ai"'
    )

    assert expected_local_url in source
    assert "return configured or LOCAL_DATABASE_URL" in source
    assert "database_unavailable" in source
    assert "local_default" in source
