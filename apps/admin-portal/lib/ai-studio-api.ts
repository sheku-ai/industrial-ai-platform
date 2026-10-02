import { platformApi, type JsonObject } from './platform-api';

export type AIStudioRuntime = {
  runtime_name: string;
  runtime_status: string;
  workspace_summary: JsonObject;
  models_and_providers: JsonObject;
  prompts: JsonObject[];
  guardrails: JsonObject[];
  workflows: JsonObject[];
  assistants: JsonObject[];
  knowledge_sources: JsonObject[];
  runtime_executions: JsonObject;
  capability_availability: JsonObject;
  policy_readiness: JsonObject;
  audit_diagnostics: JsonObject;
  diagnostics: {
    blocking_issues?: JsonObject[];
    warnings?: JsonObject[];
    pending_capabilities?: JsonObject[];
    degraded_items?: JsonObject[];
  };
  postgresql_source_of_truth: boolean;
  ai_required: boolean;
  llm_used: boolean;
  qdrant_used: boolean;
  external_provider_calls: boolean;
};

export function getAIStudioRuntime(): Promise<AIStudioRuntime> {
  return platformApi.get<AIStudioRuntime>('/api/ai/studio/runtime');
}
