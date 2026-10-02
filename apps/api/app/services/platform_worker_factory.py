from __future__ import annotations

from pathlib import Path

from app.db.session import SessionLocal
from app.repositories.lexical_index import PostgreSqlLexicalIndexRepository
from app.services.runtime_worker_bootstrap import build_runtime_worker_service
from app.services.source_acquisition import WorkspaceSourceAcquisitionService


def build_postgresql_runtime_worker(
    *,
    worker_session,
    worker_id: str,
    source_reader,
    workspace_root: Path,
    configuration,
    pipeline,
    max_source_bytes: int = 1_000_000_000,
):
    """Build the default PostgreSQL-backed runtime worker.

    Object-store access remains provider-neutral through source_reader.
    """

    if SessionLocal is None:
        raise ValueError("database url is not configured")

    acquisition = WorkspaceSourceAcquisitionService(
        source_reader,
        workspace_root,
        max_source_bytes=max_source_bytes,
    )
    return build_runtime_worker_service(
        session=worker_session,
        session_factory=SessionLocal,
        worker_id=worker_id,
        acquisition=acquisition,
        configuration=configuration,
        pipeline=pipeline,
        lexical_repository_factory=PostgreSqlLexicalIndexRepository,
    )
