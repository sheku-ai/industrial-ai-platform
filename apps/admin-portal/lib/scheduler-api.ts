import { platformApi } from './platform-api';

export type SchedulerJob = {
  id: string;
  code: string;
  name: string;
  description?: string | null;
  operation_type: string;
  enabled: boolean;
  concurrency_policy: string;
  misfire_policy: string;
  max_concurrent_runs: number;
  max_runtime_seconds?: number | null;
  parameters: Record<string, unknown>;
};

export type SchedulerSchedule = {
  id: string;
  operational_job_id: string;
  schedule_expression: string;
  timezone: string;
  enabled: boolean;
  start_at?: string | null;
  end_at?: string | null;
  next_run_at?: string | null;
  last_evaluated_at?: string | null;
};

export type SchedulerRun = {
  id: string;
  operational_job_id: string;
  schedule_id?: string | null;
  trigger_type: string;
  scheduled_for?: string | null;
  requested_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  status: string;
  runtime_execution_id?: string | null;
  error_code?: string | null;
  error_message?: string | null;
};

function headers(organizationId: string): HeadersInit {
  return {
    'X-Authorization-Scope': 'organization',
    'X-Organization-ID': organizationId,
  };
}

export const schedulerApi = {
  listJobs: (organizationId: string) =>
    platformApi.get<SchedulerJob[]>('/api/control-plane/scheduler/jobs', headers(organizationId)),
  createJob: (organizationId: string, payload: Record<string, unknown>) =>
    platformApi.post<SchedulerJob>('/api/control-plane/scheduler/jobs', payload, headers(organizationId)),
  updateJob: (organizationId: string, jobId: string, payload: Record<string, unknown>) =>
    platformApi.patch<SchedulerJob>(`/api/control-plane/scheduler/jobs/${jobId}`, payload, headers(organizationId)),
  listSchedules: (organizationId: string) =>
    platformApi.get<SchedulerSchedule[]>('/api/control-plane/scheduler/schedules', headers(organizationId)),
  createSchedule: (organizationId: string, payload: Record<string, unknown>) =>
    platformApi.post<SchedulerSchedule>('/api/control-plane/scheduler/schedules', payload, headers(organizationId)),
  updateSchedule: (organizationId: string, scheduleId: string, payload: Record<string, unknown>) =>
    platformApi.patch<SchedulerSchedule>(`/api/control-plane/scheduler/schedules/${scheduleId}`, payload, headers(organizationId)),
  listRuns: (organizationId: string, limit = 100) =>
    platformApi.get<SchedulerRun[]>(`/api/control-plane/scheduler/runs?limit=${limit}`, headers(organizationId)),
  evaluate: (organizationId: string, limit = 100) =>
    platformApi.post('/api/control-plane/scheduler/evaluate', { limit }, headers(organizationId)),
  trigger: (organizationId: string, jobId: string, idempotencyKey: string) =>
    platformApi.post<SchedulerRun>(
      `/api/control-plane/scheduler/jobs/${jobId}/runs`,
      { idempotency_key: idempotencyKey, parameters_override: {} },
      headers(organizationId),
    ),
};
