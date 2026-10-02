import { platformApi, type JsonObject } from './platform-api';

export type SchedulerBackgroundServicesRuntime = {
  runtime_name: string;
  runtime_status: string;
  workspace_summary: JsonObject;
  scheduler_summary: JsonObject;
  background_services: JsonObject[];
  worker_inventory: JsonObject[];
  worker_health: JsonObject;
  worker_activity: JsonObject;
  lease_management: JsonObject;
  lease_diagnostics: JsonObject;
  retry_engine: JsonObject;
  runtime_executions: JsonObject;
  execution_history: JsonObject;
  background_pipelines: JsonObject[];
  pipeline_health: JsonObject;
  pipeline_dependencies: JsonObject;
  runtime_readiness: JsonObject;
  operational_diagnostics: JsonObject;
  runtime_recommendations: JsonObject[];
  reference_tenant: JsonObject;
  pending_capabilities: JsonObject[];
  warnings: JsonObject[];
  postgresql_source_of_truth: boolean;
  side_effects_performed: boolean;
  external_calls_performed: boolean;
  llm_used: boolean;
  qdrant_used: boolean;
};

export function getSchedulerBackgroundServicesRuntime(): Promise<SchedulerBackgroundServicesRuntime> {
  return platformApi.get<SchedulerBackgroundServicesRuntime>(
    '/api/scheduler/background-services/center/runtime',
    { 'X-Authorization-Scope': 'platform' },
  );
}
