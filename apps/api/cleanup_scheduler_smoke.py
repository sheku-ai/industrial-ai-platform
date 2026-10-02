import sys
from uuid import UUID

from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.models.control_plane import OperationalJob, OperationalSchedule, SchedulerRun
from app.models.runtime import RuntimeExecution

job_id = UUID(sys.argv[1])

with SessionLocal() as db:
    execution_ids = list(
        db.scalars(
            select(SchedulerRun.runtime_execution_id).where(
                SchedulerRun.operational_job_id == job_id,
                SchedulerRun.runtime_execution_id.is_not(None),
            )
        )
    )
    if execution_ids:
        db.execute(delete(RuntimeExecution).where(RuntimeExecution.id.in_(execution_ids)))
    db.execute(delete(SchedulerRun).where(SchedulerRun.operational_job_id == job_id))
    db.execute(delete(OperationalSchedule).where(OperationalSchedule.operational_job_id == job_id))
    db.execute(delete(OperationalJob).where(OperationalJob.id == job_id))
    db.commit()
