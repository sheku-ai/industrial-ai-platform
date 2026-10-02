from __future__ import annotations

import json
from collections import Counter

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.core import Organization

PROTECTED_SLUGS = {
    "default-organization",
    "smoke-org",
}

LEGACY_PREFIXES = (
    "smoke-",
    "runtime-pg-",
    "integration-",
    "worker-e2e-",
    "worker-source-e2e-",
    "worker-visual-",
    "multimodal-",
    "visual-revision-",
    "visual-concurrency-",
    "revision-selection-",
    "lease-retry-",
    "lease-exhaust-",
    "lease-invalid-",
    "lease-concurrency-",
)


def classify(organization: Organization) -> str | None:
    if organization.slug in PROTECTED_SLUGS:
        return None

    config = organization.config or {}
    if config.get("lifecycle") == "ephemeral" and config.get("environment") == "test":
        return str(config.get("test_suite") or "ephemeral")
    if organization.slug.startswith(LEGACY_PREFIXES):
        return "legacy-pattern"
    return None


def main() -> int:
    if SessionLocal is None:
        raise RuntimeError("database url is not configured")

    with SessionLocal() as session:
        organizations = list(session.scalars(select(Organization).order_by(Organization.created_at)).all())

    candidates = []
    counts: Counter[str] = Counter()
    for organization in organizations:
        category = classify(organization)
        if category is None:
            continue
        counts[category] += 1
        candidates.append(
            {
                "id": str(organization.id),
                "slug": organization.slug,
                "name": organization.name,
                "category": category,
                "created_at": organization.created_at.isoformat(),
                "expires_at": (organization.config or {}).get("expires_at"),
            }
        )

    result = {
        "mode": "preview",
        "total_organizations": len(organizations),
        "candidate_count": len(candidates),
        "counts_by_category": dict(sorted(counts.items())),
        "protected_count": len(organizations) - len(candidates),
        "protected_slugs": sorted(PROTECTED_SLUGS),
        "candidates": candidates,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
