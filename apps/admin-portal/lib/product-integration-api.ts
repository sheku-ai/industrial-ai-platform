import { platformApi, type JsonObject } from './platform-api';

export type ProductIntegrationRuntime = {
  runtime_name: string;
  runtime_status: string;
  platform: JsonObject;
  administration: JsonObject;
  documents: JsonObject;
  knowledge: JsonObject;
  assistants: JsonObject;
  operations: JsonObject;
  governance: JsonObject;
  connectors: JsonObject;
  ai_studio: JsonObject;
  workspace_validation: JsonObject;
  runtime_validation: JsonObject;
  reference_tenant: JsonObject;
  domain_readiness: JsonObject;
  rc_gate: JsonObject;
  product_acceptance: JsonObject;
  evidence_freshness: JsonObject;
  release_eligibility: JsonObject;
  overall: JsonObject;
  product_score: JsonObject;
  readiness_matrix: JsonObject;
  diagnostics: {
    blocking_issues?: JsonObject[];
    warnings?: JsonObject[];
    pending_capabilities?: JsonObject[];
    recommendations?: JsonObject[];
  };
  postgresql_source_of_truth: boolean;
  side_effects_performed: boolean;
  external_calls_performed: boolean;
  llm_used: boolean;
  qdrant_used: boolean;
};

export function getProductIntegrationRuntime(): Promise<ProductIntegrationRuntime> {
  return platformApi.get<ProductIntegrationRuntime>('/api/platform/product/integration/runtime');
}
