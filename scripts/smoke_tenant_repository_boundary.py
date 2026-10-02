#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPOSITORY_ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from app.models.documents import DocumentRecord, DocumentType  # noqa: E402
from app.models.security import Permission  # noqa: E402
from app.repositories.scoped import (  # noqa: E402
    GlobalPlatformRepository,
    PlatformContextRequired,
    SharedSystemRepository,
    TenantBoundaryViolation,
    TenantContextRequired,
    TenantScopedRepository,
)
from app.security.context import (  # noqa: E402
    OrganizationContext,
    RequestSource,
    build_internal_service_context,
)


class ScalarResult:
    def all(self):
        return []


class FakeSession:
    def __init__(self) -> None:
        self.statements = []
        self.added = []
        self.deleted = []
        self.flush_count = 0

    def scalars(self, statement):
        self.statements.append(statement)
        return ScalarResult()

    def scalar(self, statement):
        self.statements.append(statement)
        return None

    def add(self, item):
        self.added.append(item)

    def delete(self, item):
        self.deleted.append(item)

    def flush(self):
        self.flush_count += 1

    def commit(self):
        raise AssertionError("scoped repositories must not commit")


def expect_error(error_type, factory) -> None:
    try:
        factory()
    except error_type:
        return
    raise AssertionError(f"expected {error_type.__name__}")


def main() -> int:
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()

    context_a = build_internal_service_context(
        service_identity="tenant-a-service",
        correlation_id="smoke-18-3-a",
        organization=OrganizationContext(
            organization_id=org_a,
            organization_path=(org_a,),
            membership_source="smoke-test",
        ),
        source=RequestSource.INTERNAL,
    )
    context_b = build_internal_service_context(
        service_identity="tenant-b-service",
        correlation_id="smoke-18-3-b",
        organization=OrganizationContext(
            organization_id=org_b,
            organization_path=(org_b,),
            membership_source="smoke-test",
        ),
        source=RequestSource.INTERNAL,
    )
    platform_context = build_internal_service_context(
        service_identity="platform-service",
        correlation_id="smoke-18-3-platform",
        source=RequestSource.INTERNAL,
    )

    db = FakeSession()

    tenant_repo = TenantScopedRepository(DocumentRecord)
    tenant_repo.list(db, context_a)
    tenant_repo.get(db, context_a, uuid.uuid4())

    compiled = "\n".join(str(statement) for statement in db.statements)
    assert "organization_id" in compiled

    created = tenant_repo.create(
        db,
        context_a,
        {
            "title": "Scoped document",
            "source_type": "smoke",
            "source_ref": {},
            "metadata_json": {},
            "classification": {},
        },
    )
    assert created.organization_id == org_a
    assert db.flush_count == 1

    expect_error(
        TenantBoundaryViolation,
        lambda: tenant_repo.create(
            db,
            context_a,
            {
                "organization_id": org_b,
                "title": "Cross tenant",
                "source_type": "smoke",
                "source_ref": {},
                "metadata_json": {},
                "classification": {},
            },
        ),
    )
    expect_error(TenantContextRequired, lambda: tenant_repo.list(db, platform_context))

    foreign_item = DocumentRecord(
        organization_id=org_b,
        title="Foreign",
        source_type="smoke",
        source_ref={},
        metadata_json={},
        classification={},
    )
    expect_error(TenantBoundaryViolation, lambda: tenant_repo.update(db, context_a, foreign_item, {"title": "Denied"}))
    expect_error(TenantBoundaryViolation, lambda: tenant_repo.delete(db, context_a, foreign_item))

    shared_repo = SharedSystemRepository(DocumentType)
    shared_repo.list(db, context_a)
    shared_created = shared_repo.create(db, context_a, {"code": "tenant-type", "name": "Tenant type"})
    assert shared_created.organization_id == org_a
    baseline_created = shared_repo.create(db, platform_context, {"code": "baseline", "name": "Baseline"})
    assert baseline_created.organization_id is None
    expect_error(TenantBoundaryViolation, lambda: shared_repo.update(db, context_a, baseline_created, {"name": "Denied"}))

    global_repo = GlobalPlatformRepository(Permission)
    global_repo.list(db, platform_context)
    expect_error(PlatformContextRequired, lambda: global_repo.list(db, context_b))

    assert db.flush_count == 3

    print(
        json.dumps(
            {
                "status": "passed",
                "contract": "RepositoryBoundaries",
                "tenant_scope_enforced": True,
                "cross_organization_write_rejected": True,
                "shared_baseline_protected": True,
                "global_scope_explicit": True,
                "repository_commit_count": 0,
                "provider_execution_enabled": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
