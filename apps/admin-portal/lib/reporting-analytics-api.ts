import { platformApi, type JsonObject } from './platform-api';

export type ReportingAnalyticsRuntime = {
  runtime_name: string;
  runtime_status: string;
  workspace_summary: JsonObject;
  platform_summary: JsonObject;
  executive_kpis: JsonObject;
  document_analytics: JsonObject;
  knowledge_analytics: JsonObject;
  enterprise_search_analytics: JsonObject;
  assistant_analytics: JsonObject;
  conversation_analytics: JsonObject;
  workflow_analytics: JsonObject;
  scheduler_analytics: JsonObject;
  background_services_analytics: JsonObject;
  connector_analytics: JsonObject;
  security_analytics: JsonObject;
  governance_analytics: JsonObject;
  audit_analytics: JsonObject;
  feedback_analytics: JsonObject;
  reference_tenant_analytics: JsonObject;
  product_readiness_trends: JsonObject;
  runtime_health_trends: JsonObject;
  operational_trends: JsonObject;
  readiness_scores: JsonObject;
  diagnostics: JsonObject;
  recommendations: JsonObject[];
  warnings: JsonObject[];
  postgresql_source_of_truth: boolean;
  side_effects_performed: boolean;
  external_calls_performed: boolean;
  llm_used: boolean;
  qdrant_used: boolean;
};

export function getReportingAnalyticsRuntime(): Promise<ReportingAnalyticsRuntime> {
  return platformApi.get<ReportingAnalyticsRuntime>('/api/reporting/analytics/center/runtime', undefined, 30_000);
}
