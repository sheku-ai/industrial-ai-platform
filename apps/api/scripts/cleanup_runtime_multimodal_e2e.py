from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.models.core import Organization
from app.models.documents import Chunk, DocumentRecord, DocumentVersion
from app.models.runtime import RuntimeExecution


def main():
    db = SessionLocal()
    try:
        rows = list(db.scalars(select(Organization).where(Organization.slug.like("runtime-e2e-%"))).all())
        for row in rows:
            db.execute(delete(RuntimeExecution).where(RuntimeExecution.organization_id == row.id))
            db.execute(delete(Chunk).where(Chunk.organization_id == row.id))
            db.execute(delete(DocumentVersion).where(DocumentVersion.organization_id == row.id))
            db.execute(delete(DocumentRecord).where(DocumentRecord.organization_id == row.id))
            db.delete(row)
        db.commit()
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
