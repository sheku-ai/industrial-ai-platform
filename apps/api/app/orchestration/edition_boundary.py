from dataclasses import dataclass
from enum import StrEnum


class PlatformEdition(StrEnum):
    COMMUNITY = "community"
    ENTERPRISE = "enterprise"


class RuntimeCapability(StrEnum):
    SYNC_EXECUTION = "sync_execution"
    STATE_MACHINE = "state_machine"
    LOCAL_ADAPTERS = "local_adapters"
    TIMEOUTS = "timeouts"
    RETRIES = "retries"
    LOCAL_AUDIT = "local_audit"
    DISTRIBUTED_EXECUTION = "distributed_execution"
    ADVANCED_ROUTING = "advanced_routing"
    MULTI_REGION = "multi_region"
    CENTRAL_AUDIT_EXPORT = "central_audit_export"


COMMUNITY_RUNTIME_CAPABILITIES = frozenset(
    {
        RuntimeCapability.SYNC_EXECUTION,
        RuntimeCapability.STATE_MACHINE,
        RuntimeCapability.LOCAL_ADAPTERS,
        RuntimeCapability.TIMEOUTS,
        RuntimeCapability.RETRIES,
        RuntimeCapability.LOCAL_AUDIT,
    }
)

ENTERPRISE_RUNTIME_CAPABILITIES = frozenset(
    {
        RuntimeCapability.DISTRIBUTED_EXECUTION,
        RuntimeCapability.ADVANCED_ROUTING,
        RuntimeCapability.MULTI_REGION,
        RuntimeCapability.CENTRAL_AUDIT_EXPORT,
    }
)


@dataclass(frozen=True)
class EditionRuntimeCapabilities:
    edition: PlatformEdition
    capabilities: frozenset[RuntimeCapability]

    def supports(self, capability: RuntimeCapability) -> bool:
        return capability in self.capabilities


def runtime_capabilities_for(edition: PlatformEdition) -> EditionRuntimeCapabilities:
    capabilities = COMMUNITY_RUNTIME_CAPABILITIES
    if edition == PlatformEdition.ENTERPRISE:
        capabilities = capabilities | ENTERPRISE_RUNTIME_CAPABILITIES
    return EditionRuntimeCapabilities(edition=edition, capabilities=capabilities)
