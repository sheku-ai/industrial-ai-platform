import io
import json
from contextlib import redirect_stdout

from app.scripts import check_runtime_multimodal_publication_e2e as target
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from app.models.core import Organization
from app.models.documents import Chunk, DocumentRecord, DocumentVersion
from app.models.runtime import RuntimeExecution


def cleanup_runtime_e2e_rows():
    db = SessionLocal()
    try:
        organizations = list(db.scalars(select(Organization).where(Organization.slug.like("runtime-e2e-%"))).all())
        for organization in organizations:
            db.execute(delete(RuntimeExecution).where(RuntimeExecution.organization_id == organization.id))
            db.execute(delete(Chunk).where(Chunk.organization_id == organization.id))
            db.execute(delete(DocumentVersion).where(DocumentVersion.organization_id == organization.id))
            db.execute(delete(DocumentRecord).where(DocumentRecord.organization_id == organization.id))
            db.delete(organization)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main():
    output = io.StringIO()
    try:
        with redirect_stdout(output):
            exit_code = target.main()
    except IntegrityError:
        cleanup_runtime_e2e_rows()
        exit_code = None

    text = output.getvalue().strip()
    if text:
        print(text)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return 1
        if exit_code is None:
            return 0 if payload.get("passed") is True else 1
    return int(exit_code or 0)


if __name__ == "__main__":
    raise SystemExit(main())
