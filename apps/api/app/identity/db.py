from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.identity.base import IdentityBase


settings = get_settings()
identity_engine = (
    create_engine(
        settings.identity_database_url,
        pool_pre_ping=True,
        pool_recycle=1_800,
    )
    if settings.identity_database_url
    else None
)
IdentitySessionLocal = (
    sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=identity_engine)
    if identity_engine is not None
    else None
)


def get_identity_db() -> Generator[Session, None, None]:
    if IdentitySessionLocal is None:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="identity_service_unavailable",
        )
    db = IdentitySessionLocal()
    try:
        yield db
    finally:
        db.close()
