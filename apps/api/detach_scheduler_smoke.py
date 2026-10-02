import sys
from uuid import UUID

from sqlalchemy import update

from app.db.session import SessionLocal
from app.models.control_plane import SchedulerRun

job_id = UUID(sys.argv[1])

with SessionLocal() as db:
    db.execute(
        update(SchedulerRun)
        .where(SchedulerRun.operational_job_id == job_id)
        .values(runtime_execution_id=None)
    )
    db.commit()
