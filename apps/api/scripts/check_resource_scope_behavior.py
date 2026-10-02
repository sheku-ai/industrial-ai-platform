from __future__ import annotations

import json
from uuid import uuid4

from app.security.resource_scope import ResourceScope, ResourceScopeType


def expect_error(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    return False


def main() -> int:
    org_a = uuid4()
    org_b = uuid4()
    workload_a = ResourceScope.workload(org_a, resource_id="workload-a")

    checks = {
        "platform_global": ResourceScope.platform().organization_id is None,
        "platform_rejects_organization": expect_error(
            lambda: ResourceScope(scope_type=ResourceScopeType.PLATFORM, organization_id=org_a)
        ),
        "organization_requires_organization": expect_error(
            lambda: ResourceScope.from_values(scope_type="organization", organization_id=None)
        ),
        "workload_requires_organization": expect_error(
            lambda: ResourceScope.from_values(scope_type="workload", organization_id=None, resource_id="w")
        ),
        "workload_requires_resource_id": expect_error(
            lambda: ResourceScope.from_values(scope_type="workload", organization_id=org_a)
        ),
        "workload_in_organization": workload_a.is_within(ResourceScope.organization(org_a)),
        "workload_not_in_other_organization": not workload_a.is_within(ResourceScope.organization(org_b)),
        "organization_not_in_workload": not ResourceScope.organization(org_a).is_within(workload_a),
        "persisted_platform_assignment_is_global": ResourceScope.from_persisted_assignment(
            scope_type="platform", scope_id="platform", organization_id=None
        )
        == ResourceScope.platform(),
        "persisted_workload_assignment_resolves": ResourceScope.from_persisted_assignment(
            scope_type="workload", scope_id="workload-a", organization_id=org_a
        )
        == workload_a,
    }
    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
