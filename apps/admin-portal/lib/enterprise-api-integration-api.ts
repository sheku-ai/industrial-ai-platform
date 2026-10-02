import { platformApi, type JsonObject } from './platform-api';

export type EnterpriseApiIntegrationRuntime = {
  runtime_name: string;
  runtime_status: string;
  workspace_summary: JsonObject;
  platform_api_inventory: JsonObject;
  endpoint_catalog: JsonObject[];
  runtime_endpoint_catalog: JsonObject[];
  api_groups: JsonObject;
  versioning: JsonObject;
  authentication_methods: JsonObject;
  authorization_model: JsonObject;
  security_scopes: JsonObject;
  jwt_readiness: JsonObject;
  service_endpoints: JsonObject;
  external_integrations: JsonObject;
  connector_integrations: JsonObject;
  webhook_inventory: JsonObject;
  event_catalog: JsonObject;
  integration_diagnostics: JsonObject;
  api_readiness: JsonObject;
  reference_tenant_integration_readiness: JsonObject;
  operational_recommendations: JsonObject[];
  warnings: JsonObject[];
  postgresql_source_of_truth: boolean;
  side_effects_performed: boolean;
  external_calls_performed: boolean;
  llm_used: boolean;
  qdrant_used: boolean;
};

export function getEnterpriseApiIntegrationRuntime(): Promise<EnterpriseApiIntegrationRuntime> {
  return platformApi.get<EnterpriseApiIntegrationRuntime>('/api/enterprise/api-integration/center/runtime');
}
