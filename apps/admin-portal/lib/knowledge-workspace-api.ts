import { platformApi, type JsonObject } from './platform-api';

export type KnowledgeWorkspaceCollection = {
  collection_id: string;
  code: string;
  name: string;
  status: string;
  document_count: number;
  knowledge_document_count: number;
  chunk_count: number;
  source_count: number;
  readiness: JsonObject;
};

export type KnowledgeWorkspaceSource = {
  source_id: string;
  collection_id?: string | null;
  source_type: string;
  source_status: string;
  readiness: string;
  configured: boolean;
};

export type KnowledgeWorkspaceDocument = {
  knowledge_document_id: string;
  document_record_id?: string | null;
  document_version_id?: string | null;
  artifact_id?: string | null;
  collection_id?: string | null;
  title?: string | null;
  status: string;
  chunk_count: number;
  indexed_at?: string | null;
  created_at?: string | null;
  readiness: JsonObject;
};

export type KnowledgeWorkspaceRuntime = {
  runtime_name: string;
  runtime_status: string;
  workspace_summary: JsonObject;
  collections: KnowledgeWorkspaceCollection[];
  knowledge_sources: KnowledgeWorkspaceSource[];
  knowledge_documents: KnowledgeWorkspaceDocument[];
  chunk_overview: JsonObject;
  enterprise_search: JsonObject;
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

export function getKnowledgeWorkspaceRuntime(): Promise<KnowledgeWorkspaceRuntime> {
  return platformApi.get<KnowledgeWorkspaceRuntime>('/api/knowledge/workspace/runtime');
}
