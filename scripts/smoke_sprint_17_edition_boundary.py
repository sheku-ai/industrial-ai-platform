from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.orchestration import (
    COMMUNITY_RUNTIME_CAPABILITIES,
    ENTERPRISE_RUNTIME_CAPABILITIES,
    PlatformEdition,
    RuntimeCapability,
    runtime_capabilities_for,
)


def main() -> None:
    community = runtime_capabilities_for(PlatformEdition.COMMUNITY)
    enterprise = runtime_capabilities_for(PlatformEdition.ENTERPRISE)

    assert community.capabilities == COMMUNITY_RUNTIME_CAPABILITIES
    assert enterprise.capabilities == COMMUNITY_RUNTIME_CAPABILITIES | ENTERPRISE_RUNTIME_CAPABILITIES
    assert community.supports(RuntimeCapability.SYNC_EXECUTION)
    assert community.supports(RuntimeCapability.STATE_MACHINE)
    assert community.supports(RuntimeCapability.LOCAL_ADAPTERS)
    assert not community.supports(RuntimeCapability.DISTRIBUTED_EXECUTION)
    assert not community.supports(RuntimeCapability.MULTI_REGION)
    assert enterprise.supports(RuntimeCapability.DISTRIBUTED_EXECUTION)
    assert enterprise.supports(RuntimeCapability.ADVANCED_ROUTING)
    assert enterprise.supports(RuntimeCapability.MULTI_REGION)
    assert COMMUNITY_RUNTIME_CAPABILITIES.isdisjoint(ENTERPRISE_RUNTIME_CAPABILITIES)

    print(
        {
            "status": "passed",
            "community_runtime_complete": True,
            "enterprise_additive_only": True,
            "capability_sets_disjoint": True,
            "community_without_enterprise_dependency": True,
            "provider_execution_performed": False,
            "network_call_performed": False,
            "generation_performed": False,
        }
    )


if __name__ == "__main__":
    main()
