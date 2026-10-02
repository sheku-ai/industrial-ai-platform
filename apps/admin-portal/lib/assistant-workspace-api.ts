import { organizationHeaders, platformApi, type JsonObject } from './platform-api';

export type AssistantDefinitionItem = {
  assistant_id: string;
  assistant_key: string;
  assistant_name: string;
  assistant_status: string;
  assistant_version: string;
  assistant_type: string;
  description?: string | null;
  default_search_mode: string;
  allowed_runtime_domains: string[];
  guardrail_profile: JsonObject;
  runtime_metadata?: JsonObject;
  prompt_profile?: unknown;
  knowledge_sources: JsonObject[];
  availability: JsonObject;
  readiness: JsonObject;
};

export type AssistantConversationItem = {
  conversation_id: string;
  assistant_id?: string | null;
  status: string;
  title?: string | null;
  turn_count: number;
  last_activity_at?: string | null;
  readiness: JsonObject;
};

export type AssistantWorkspaceRuntime = {
  runtime_name: string;
  runtime_status: string;
  workspace_summary: JsonObject;
  assistant_definitions: AssistantDefinitionItem[];
  conversations: AssistantConversationItem[];
  conversation_turns: JsonObject[];
  runtime_executions: JsonObject;
  retrieval_and_citations: JsonObject;
  feedback_and_audit: JsonObject;
  assistant_explorer?: JsonObject;
  conversation_explorer?: JsonObject;
  conversation_timeline?: JsonObject;
  retrieval_explorer?: JsonObject;
  citation_explorer?: JsonObject;
  runtime_execution?: JsonObject;
  feedback?: JsonObject;
  audit?: JsonObject;
  runtime_trace?: JsonObject;
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
};

export type AssistantWorkspaceCapabilities = {
  organization_id?: string | null;
  assistant_read: boolean;
  assistant_administer: boolean;
  workspace_available: boolean;
  chat_available: boolean;
  conversations_available: boolean;
  reason?: string | null;
};

export function getAssistantWorkspaceCapabilities(organizationId: string): Promise<AssistantWorkspaceCapabilities> {
  return platformApi.get<AssistantWorkspaceCapabilities>(
    '/api/assistants/workspace/capabilities',
    organizationHeaders(organizationId),
  );
}

export function getAssistantWorkspaceRuntime(organizationId: string): Promise<AssistantWorkspaceRuntime> {
  return platformApi.get<AssistantWorkspaceRuntime>(
    '/api/assistants/workspace/runtime',
    organizationHeaders(organizationId),
  );
}
