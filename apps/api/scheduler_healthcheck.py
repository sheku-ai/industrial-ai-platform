from __future__ import annotations

import json
import os
import sys

from app.db.session import SessionLocal
from app.services.scheduler_health import evaluate_scheduler_operational_health


def main() -> int:
    if SessionLocal is None:
        print("scheduler healthcheck failed: database url is not configured", file=sys.stderr)
        return 1

    owner_id = os.getenv("SCHEDULER_OWNER_ID", "scheduler-daemon")
    heartbeat_stale_seconds = max(
        5,
        int(os.getenv("SCHEDULER_HEALTH_HEARTBEAT_STALE_SECONDS", "30")),
    )
    cycle_stale_seconds = max(
        heartbeat_stale_seconds,
        int(os.getenv("SCHEDULER_HEALTH_CYCLE_STALE_SECONDS", "60")),
    )

    session = SessionLocal()
    try:
        snapshot = evaluate_scheduler_operational_health(
            session,
            owner_id=owner_id,
            heartbeat_stale_seconds=heartbeat_stale_seconds,
            cycle_stale_seconds=cycle_stale_seconds,
        )
    except Exception as exc:
        session.rollback()
        print(f"scheduler healthcheck failed: {exc}", file=sys.stderr)
        return 1
    finally:
        session.close()

    print(
        json.dumps(
            {
                "healthy": snapshot.healthy,
                "reason": snapshot.reason,
                "owner_id": snapshot.owner_id,
                "status": snapshot.status,
                "heartbeat_at": snapshot.heartbeat_at.isoformat() if snapshot.heartbeat_at else None,
                "last_cycle_completed_at": (
                    snapshot.last_cycle_completed_at.isoformat()
                    if snapshot.last_cycle_completed_at
                    else None
                ),
                "cycles_completed": snapshot.cycles_completed,
            },
            sort_keys=True,
        )
    )
    return 0 if snapshot.healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
