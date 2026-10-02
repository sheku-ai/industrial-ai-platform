from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.security.tenant_session import configure_tenant_session_boundary

settings = get_settings()
engine = create_engine(settings.database_url) if settings.database_url else None
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine) if engine else None
configure_tenant_session_boundary()


def get_db() -> Generator[Session, None, None]:
    if SessionLocal is None:
        raise ValueError("database url is not configured")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
