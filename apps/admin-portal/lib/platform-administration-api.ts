import { platformApi, type JsonObject } from './platform-api';

export type PlatformAdministrationRuntime = {
  runtime_name: string;
  runtime_status: string;
  platform: JsonObject;
  organizations: JsonObject;
  security: JsonObject;
  documents: JsonObject;
  knowledge: JsonObject;
  enterprise_search: JsonObject;
  assistants: JsonObject;
  reference_tenant: JsonObject;
  health_summary: JsonObject;
  data_scope: JsonObject;
  warnings: JsonObject[];
  blocking_issues: JsonObject[];
  postgresql_source_of_truth: boolean;
  llm_used: boolean;
  embeddings_used: boolean;
  qdrant_used: boolean;
};

export function getPlatformAdministrationRuntime(includeValidation = false): Promise<PlatformAdministrationRuntime> {
  const query = includeValidation ? '?include_validation=true' : '';
  return platformApi.get<PlatformAdministrationRuntime>(`/api/platform/administration/runtime${query}`);
}
