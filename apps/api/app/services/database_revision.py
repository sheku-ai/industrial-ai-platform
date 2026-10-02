from sqlalchemy import text
from sqlalchemy.orm import Session


def resolve_database_revision(session: Session | None) -> str:
    if session is None:
        return "unavailable"
    try:
        values = session.execute(text("SELECT version_num FROM alembic_version ORDER BY version_num")).scalars().all()
    except Exception:
        session.rollback()
        return "unavailable"
    return ",".join(values) if values else "unversioned"
