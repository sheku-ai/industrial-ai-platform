from pathlib import Path

import pytest

from app.repositories.lexical_index import PostgreSqlLexicalIndexRepository
from app.services.platform_worker_factory import build_postgresql_runtime_worker
from app.services.source_acquisition import WorkspaceSourceAcquisitionService


def test_factory_requires_database_configuration(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("app.services.platform_worker_factory.SessionLocal", None)

    with pytest.raises(ValueError, match="database url is not configured"):
        build_postgresql_runtime_worker(
            worker_session=object(),
            worker_id="worker-1",
            source_reader=object(),
            workspace_root=tmp_path,
            configuration=object(),
            pipeline=object(),
        )


def test_factory_uses_workspace_acquisition_and_postgresql_lexical_repository(monkeypatch, tmp_path: Path):
    captured = {}

    def session_factory():
        return object()

    monkeypatch.setattr("app.services.platform_worker_factory.SessionLocal", session_factory)

    def fake_builder(**kwargs):
        captured.update(kwargs)
        return "worker"

    monkeypatch.setattr("app.services.platform_worker_factory.build_runtime_worker_service", fake_builder)

    result = build_postgresql_runtime_worker(
        worker_session=object(),
        worker_id="worker-1",
        source_reader=object(),
        workspace_root=tmp_path,
        configuration=object(),
        pipeline=object(),
        max_source_bytes=1024,
    )

    assert result == "worker"
    assert captured["session_factory"] is session_factory
    assert captured["lexical_repository_factory"] is PostgreSqlLexicalIndexRepository
    assert isinstance(captured["acquisition"], WorkspaceSourceAcquisitionService)
