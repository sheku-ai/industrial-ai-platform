import { platformApi, type JsonObject } from './platform-api';

export type PlatformDashboardNavigationItem = {
  key: string;
  label: string;
  path: string;
  readiness: string;
  status: string;
  count?: number;
};

export type PlatformDashboardAction = {
  key: string;
  label: string;
  reason?: string;
  domains?: string[];
};

export type PlatformDashboardSections = {
  platform_health?: JsonObject;
  organizations?: JsonObject;
  documents?: JsonObject;
  knowledge?: JsonObject;
  enterprise_search?: JsonObject;
  conversations?: JsonObject;
  workers?: JsonObject;
  scheduler?: JsonObject;
  runtime_executions?: JsonObject;
  storage?: JsonObject;
  connectors?: JsonObject;
  ai?: JsonObject;
  recent_activity?: JsonObject[];
};

export type PlatformDashboardRuntime = {
  runtime_name: string;
  runtime_status: string;
  platform_summary: JsonObject;
  administration_summary: JsonObject;
  operations_summary: JsonObject;
  readiness_summary: Record<string, boolean>;
  operational_summary: Record<string, unknown>;
  functional_capabilities?: JsonObject;
  dashboard_sections?: PlatformDashboardSections;
  alerts_and_diagnostics: {
    blocking_issues?: JsonObject[];
    warnings?: JsonObject[];
    pending_capabilities?: JsonObject[];
    unavailable_domains?: string[];
    degraded_domains?: string[];
  };
  navigation: PlatformDashboardNavigationItem[];
  recommended_next_actions: PlatformDashboardAction[];
  postgresql_source_of_truth: boolean;
  ai_required: boolean;
  llm_used: boolean;
  embeddings_used?: boolean;
  qdrant_used: boolean;
};

export type ProductNavigationCapabilities = {
  organization_id?: string | null;
  documents: { visible: boolean; action_available: boolean };
  search: { visible: boolean; action_available: boolean };
  assistant: { visible: boolean; action_available: boolean };
  ai_configuration: {
    visible: boolean;
    administer_providers: boolean;
    administer_models: boolean;
    validate: boolean;
  };
  platform: {
    operations: PlatformCapability;
    scheduler: PlatformCapability;
    release_readiness: PlatformCapability;
  };
};

export type PlatformCapability = {
  visible: boolean;
  action_available: boolean;
};

export type PlatformCapabilityKey = keyof ProductNavigationCapabilities['platform'];

export function platformCapabilityAvailable(
  capabilities: ProductNavigationCapabilities | null,
  capability: PlatformCapabilityKey,
  action = false,
): boolean {
  const resolved = capabilities?.platform[capability];
  return Boolean(action ? resolved?.action_available : resolved?.visible);
}

export function getPlatformDashboardRuntime(): Promise<PlatformDashboardRuntime> {
  return platformApi.get<PlatformDashboardRuntime>('/api/platform/dashboard/runtime');
}

export function getProductNavigationCapabilities(): Promise<ProductNavigationCapabilities> {
  return platformApi.get<ProductNavigationCapabilities>('/api/platform/dashboard/capabilities');
}
