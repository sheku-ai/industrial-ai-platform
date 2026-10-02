import { platformApi, type JsonObject } from './platform-api';

export type ValidationEvidence = {
  id: string;
  subject_type: 'provider' | 'model';
  validation_type: string;
  status: 'succeeded' | 'failed';
  error_code: string | null;
  sanitized_error: string | null;
  evaluated_at: string;
  configuration_revision: string;
  current_configuration_revision: string;
  evidence_status: 'current' | 'stale';
  actor_reference: string | null;
  correlation_id: string | null;
  metadata: JsonObject;
};

export type ProviderAdapter = {
  adapter_type: string;
  supported_capabilities: string[];
  credential_required: boolean;
  known_type: boolean;
  configuration_supported: boolean;
  execution_supported: boolean;
  availability_reason_code: string | null;
  availability_reason: string | null;
};

export type RuntimeActionAvailability = {
  allowed: boolean;
  reason_code: string | null;
  reason: string | null;
};

export type ProviderConfiguration = {
  id: string;
  organization_id: string;
  provider_key: string;
  display_name: string;
  adapter_type: string;
  provider_type: string;
  description: string | null;
  endpoint_url: string | null;
  configuration: JsonObject;
  enabled: boolean;
  lifecycle_status: 'active' | 'archived';
  credential_configured: boolean;
  availability_status: string;
  available: boolean;
  validation_status: 'never_validated' | 'succeeded' | 'failed' | 'stale';
  latest_validation: ValidationEvidence | null;
  runtime_actions: {
    validate: RuntimeActionAvailability;
    enable: RuntimeActionAvailability;
  };
  created_at: string;
  updated_at: string;
};

export type ModelConfiguration = {
  id: string;
  organization_id: string;
  provider_configuration_id: string;
  provider_display_name: string;
  model_key: string;
  display_name: string;
  model_identifier: string;
  capability: string;
  configuration: JsonObject;
  enabled: boolean;
  lifecycle_status: 'active' | 'archived';
  default_scope: string;
  is_default: boolean;
  default_effective: boolean;
  availability_status: string;
  available: boolean;
  validation_status: 'never_validated' | 'succeeded' | 'failed' | 'stale';
  latest_validation: ValidationEvidence | null;
  runtime_actions: {
    enable: RuntimeActionAvailability;
    validate: RuntimeActionAvailability;
    set_default: RuntimeActionAvailability;
  };
  created_at: string;
  updated_at: string;
};

export type AIConfigurationWorkspace = {
  capabilities: {
    read: boolean;
    administer_providers: boolean;
    administer_models: boolean;
    validate: boolean;
  };
  adapters: ProviderAdapter[];
  model_capabilities: string[];
  credential_resolver_types: string[];
  providers: ProviderConfiguration[];
  models: ModelConfiguration[];
  provider_count: number;
  model_count: number;
  available_provider_count: number;
  available_model_count: number;
  ai_required: false;
  postgresql_source_of_truth: true;
  secrets_exposed: false;
};

export type ProviderInput = {
  provider_key: string;
  display_name: string;
  adapter_type: string;
  description?: string | null;
  endpoint_url?: string | null;
  credential?: { resolver_type: string; reference: string };
  clear_credential?: boolean;
  configuration: JsonObject;
  enabled?: boolean;
};

export type ModelInput = {
  provider_configuration_id: string;
  model_key: string;
  display_name: string;
  model_identifier: string;
  capability: string;
  configuration: JsonObject;
  enabled?: boolean;
  default_scope: string;
};

export function getAIConfigurationWorkspace(): Promise<AIConfigurationWorkspace> {
  return platformApi.get<AIConfigurationWorkspace>('/api/ai/configuration');
}

export function createProviderConfiguration(payload: ProviderInput): Promise<ProviderConfiguration> {
  return platformApi.post<ProviderConfiguration>('/api/ai/providers', payload);
}

export function updateProviderConfiguration(
  providerId: string,
  payload: Partial<ProviderInput>,
): Promise<ProviderConfiguration> {
  return platformApi.patch<ProviderConfiguration>(`/api/ai/providers/${providerId}`, payload);
}

export function setProviderEnabled(providerId: string, enabled: boolean): Promise<ProviderConfiguration> {
  return platformApi.post<ProviderConfiguration>(`/api/ai/providers/${providerId}/enabled`, { enabled });
}

export function setProviderArchived(providerId: string, archived: boolean): Promise<ProviderConfiguration> {
  return platformApi.post<ProviderConfiguration>(
    `/api/ai/providers/${providerId}/${archived ? 'archive' : 'restore'}`,
    {},
  );
}

export function validateProvider(providerId: string): Promise<ValidationEvidence> {
  return platformApi.post<ValidationEvidence>(`/api/ai/providers/${providerId}/validate`, {});
}

export function createModelConfiguration(payload: ModelInput): Promise<ModelConfiguration> {
  return platformApi.post<ModelConfiguration>('/api/ai/models', payload);
}

export function updateModelConfiguration(
  modelId: string,
  payload: Partial<ModelInput>,
): Promise<ModelConfiguration> {
  return platformApi.patch<ModelConfiguration>(`/api/ai/models/${modelId}`, payload);
}

export function setModelEnabled(modelId: string, enabled: boolean): Promise<ModelConfiguration> {
  return platformApi.post<ModelConfiguration>(`/api/ai/models/${modelId}/enabled`, { enabled });
}

export function setModelArchived(modelId: string, archived: boolean): Promise<ModelConfiguration> {
  return platformApi.post<ModelConfiguration>(
    `/api/ai/models/${modelId}/${archived ? 'archive' : 'restore'}`,
    {},
  );
}

export function setDefaultModel(modelId: string, isDefault: boolean): Promise<ModelConfiguration> {
  return platformApi.post<ModelConfiguration>(`/api/ai/models/${modelId}/default`, {
    is_default: isDefault,
  });
}

export function validateModel(modelId: string): Promise<ValidationEvidence> {
  return platformApi.post<ValidationEvidence>(`/api/ai/models/${modelId}/validate`, {});
}
