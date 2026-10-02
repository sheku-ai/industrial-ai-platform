import { platformApi, type JsonObject } from './platform-api';

export type SearchDiscoveryRuntime = {
  runtime_name: string;
  runtime_status: string;
  workspace_summary: JsonObject;
  enterprise_search_summary: JsonObject;
  knowledge_coverage: JsonObject;
  knowledge_collections: JsonObject[];
  knowledge_sources: JsonObject[];
  knowledge_documents: JsonObject[];
  knowledge_chunks: JsonObject;
  chunk_explorer: JsonObject;
  document_explorer: JsonObject;
  citation_explorer: JsonObject;
  search_explorer: JsonObject;
  search_diagnostics: JsonObject;
  coverage_diagnostics: JsonObject;
  evidence_readiness: JsonObject;
  traceability: JsonObject;
  search_performance: JsonObject;
  search_quality: JsonObject;
  reference_tenant_coverage: JsonObject;
  pending_capabilities: JsonObject[];
  warnings: JsonObject[];
  recommendations: JsonObject[];
  postgresql_source_of_truth: boolean;
  llm_used: boolean;
  qdrant_used: boolean;
};

export type EnterpriseSearchResult = {
  search_result_id: string;
  rank: number;
  score: number;
  snippet: string;
  highlighted_snippet?: string;
  text: string;
  artifact_id?: string | null;
  publication_id?: string | null;
  published_chunk_id?: string | null;
  chunk_index?: number | null;
  content_type?: string | null;
  metadata: JsonObject;
  citation: JsonObject;
};

export type EnterpriseSearchResponse = {
  search_status: string;
  query: string;
  total_count: number;
  result_count: number;
  results: EnterpriseSearchResult[];
  citations: JsonObject[];
  blocking_issues: JsonObject[];
  warnings: JsonObject[];
  search_uses_postgresql: boolean;
  search_uses_postgresql_fts: boolean;
};

export function getSearchDiscoveryRuntime(): Promise<SearchDiscoveryRuntime> {
  return platformApi.get<SearchDiscoveryRuntime>('/api/search/discovery/runtime');
}

export function executeEnterpriseSearch(query: string, contentType?: string): Promise<EnterpriseSearchResponse> {
  return platformApi.post<EnterpriseSearchResponse>('/api/enterprise-search/search', {
    query,
    top_k: 20,
    offset: 0,
    limit: 20,
    include_facets: true,
    include_debug: false,
    content_type: contentType || null,
  });
}
