import { platformApi, type JsonObject } from './platform-api';

export type GovernanceCenterRuntime = {
  runtime_name: string;
  runtime_status: string;
  workspace_summary: JsonObject;
  audit_governance: JsonObject;
  feedback_governance: JsonObject;
  classification_governance: JsonObject;
  retention_governance: JsonObject;
  policy_governance: JsonObject;
  runtime_evidence: JsonObject;
  document_lineage: JsonObject;
  knowledge_lineage: JsonObject;
  assistant_traceability: JsonObject;
  compliance_readiness: JsonObject;
  diagnostics: {
    blocking_issues?: JsonObject[];
    warnings?: JsonObject[];
    pending_capabilities?: JsonObject[];
    degraded_items?: JsonObject[];
    governance_recommendations?: JsonObject[];
  };
  postgresql_source_of_truth: boolean;
  side_effects_performed: boolean;
  llm_used: boolean;
  qdrant_used: boolean;
  external_calls_performed: boolean;
};

export function getGovernanceCenterRuntime(): Promise<GovernanceCenterRuntime> {
  return platformApi.get<GovernanceCenterRuntime>('/api/platform/governance/center/runtime');
}
