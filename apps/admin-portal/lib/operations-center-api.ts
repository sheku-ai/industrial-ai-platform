import { platformApi, type JsonObject } from './platform-api';

export type OperationsCenterRuntime = {
  runtime_name: string;
  runtime_status: string;
  authorization: {
    'platform.operations:read': boolean;
    'platform.operations:administer': boolean;
  };
  workspace_summary: JsonObject;
  runtime_persistence: JsonObject;
  document_lifecycle_operations: JsonObject;
  processing_workers: JsonObject;
  knowledge_operations: JsonObject;
  enterprise_search_operations: JsonObject;
  assistant_operations: JsonObject;
  connector_operations: JsonObject;
  feedback_audit_operations: JsonObject;
  operational_readiness: JsonObject;
  security_readiness: JsonObject;
  component_summary: JsonObject;
  worker_summary: JsonObject;
  scheduler_summary: JsonObject;
  lease_summary: JsonObject;
  execution_summary: JsonObject;
  retry_summary: JsonObject;
  incident_summary: JsonObject;
  recent_recovery_actions: JsonObject[];
  evidence_freshness: JsonObject;
  next_actions: JsonObject[];
  diagnostics: {
    blocking_issues?: JsonObject[];
    warnings?: JsonObject[];
    pending_capabilities?: JsonObject[];
    degraded_items?: JsonObject[];
    failed_items?: JsonObject[];
    retry_candidates?: JsonObject[];
    operational_recommendations?: JsonObject[];
  };
  postgresql_source_of_truth: boolean;
  side_effects_performed: boolean;
  llm_used: boolean;
  qdrant_used: boolean;
  external_calls_performed: boolean;
};

export function getOperationsCenterRuntime(): Promise<OperationsCenterRuntime> {
  return platformApi.get<OperationsCenterRuntime>(
    '/api/platform/operations/center/runtime',
    { 'X-Authorization-Scope': 'platform' },
  );
}
