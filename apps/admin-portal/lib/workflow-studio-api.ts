import { platformApi, type JsonObject } from './platform-api';

export type WorkflowStudioRuntime = {
  runtime_name: string;
  runtime_status: string;
  workspace_summary: JsonObject;
  workflow_inventory: JsonObject[];
  workflow_categories: JsonObject;
  workflow_readiness: JsonObject;
  workflow_diagnostics: JsonObject;
  workflow_dependencies: JsonObject;
  workflow_evidence: JsonObject;
  workflow_runtime_state: JsonObject;
  workflow_health: JsonObject;
  workflow_recommendations: JsonObject[];
  reference_tenant: JsonObject;
  pending_capabilities: JsonObject[];
  warnings: JsonObject[];
  postgresql_source_of_truth: boolean;
  side_effects_performed: boolean;
  external_calls_performed: boolean;
  llm_used: boolean;
  qdrant_used: boolean;
};

export function getWorkflowStudioRuntime(): Promise<WorkflowStudioRuntime> {
  return platformApi.get<WorkflowStudioRuntime>('/api/workflows/studio/runtime');
}
