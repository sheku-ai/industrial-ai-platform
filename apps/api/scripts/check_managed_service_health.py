from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.runtime_worker import RuntimeWorker


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-key", required=True)
    parser.add_argument("--max-age", type=int, default=60)
    args = parser.parse_args()

    if SessionLocal is None or args.max_age <= 0:
        return 1

    cutoff = datetime.now(UTC) - timedelta(seconds=args.max_age)
    with SessionLocal() as session:
        worker = session.scalar(select(RuntimeWorker).where(RuntimeWorker.worker_key == args.worker_key))

    if worker is None or worker.heartbeat_at is None:
        return 1
    if worker.heartbeat_at < cutoff:
        return 1
    if worker.observed_state in {"failed", "offline"}:
        return 1

    print(worker.worker_key, worker.observed_state, worker.heartbeat_at.isoformat())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
