from __future__ import annotations

import argparse
import json

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.core import Organization
from scripts.inventory_test_organizations import classify


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--value-only", action="store_true")
    args = parser.parse_args()

    if SessionLocal is None:
        raise RuntimeError("database url is not configured")

    with SessionLocal() as session:
        organizations = list(session.scalars(select(Organization)).all())

    candidate_count = sum(1 for organization in organizations if classify(organization) is not None)
    if args.value_only:
        print(candidate_count)
    else:
        print(
            json.dumps(
                {
                    "total_organizations": len(organizations),
                    "test_organization_candidates": candidate_count,
                },
                indent=2,
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
