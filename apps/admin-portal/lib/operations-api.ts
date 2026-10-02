import { platformApi } from './platform-api';

const REQUEST_TIMEOUT_MS = 15000;

export type HealthStatus = 'healthy' | 'degraded' | 'critical' | 'unknown';

export type OperationalHealthIssue = {
  code: string;
  severity: 'degraded' | 'critical';
  source: string;
  resource_type: string;
  resource_key?: string | null;
  message: string;
  observed_value?: number | string | null;
};

export type SchedulerHealth = {
  enabled_jobs: number;
  disabled_jobs: number;
  enabled_schedules: number;
  overdue_schedules: number;
  schedules_without_next_run: number;
  pending_runs: number;
  active_runs: number;
  failed_runs: number;
  oldest_pending_run_at?: string | null;
  expired_claims: number;
  latest_success_at?: string | null;
  latest_failure_at?: string | null;
};

export type OperationalHealth = {
  summary: { organization_id: string; overall_status: HealthStatus; active_issues: number; calculated_at: string };
  scheduler: SchedulerHealth;
  issues: OperationalHealthIssue[];
  runtime: Record<string, number | string | null>;
  artifact_publications: Record<string, number | string | null>;
  reconciliation: {
    candidate_count: number;
    oldest_candidate_at?: string | null;
    missing_candidates: number;
    checksum_conflict_candidates: number;
    last_manual_run_at?: string | null;
    last_successful_run_at?: string | null;
    last_failed_run_at?: string | null;
  };
  freshness: { calculated_at: string; data_max_timestamp?: string | null; age_seconds?: number | null; is_stale: boolean };
};

export type ReconciliationItem = {
  source_publication_id: string;
  resulting_publication_id?: string | null;
  outcome: string;
  changed: boolean;
  error_code?: string | null;
};

export type ReconciliationResponse = {
  mode: 'preview' | 'run';
  scanned: number;
  processed: number;
  changed: number;
  verified: number;
  missing: number;
  checksum_conflict: number;
  unchanged: number;
  failed: number;
  next_cursor?: string | null;
  items: ReconciliationItem[];
};

function headers(organizationId: string): HeadersInit {
  return {
    'X-Authorization-Scope': 'organization',
    'X-Organization-ID': organizationId,
  };
}

function bounded<T>(request: Promise<T>, label: string): Promise<T> {
  return Promise.race([
    request,
    new Promise<never>((_, reject) => {
      setTimeout(
        () => reject(new Error(`${label} timed out after ${REQUEST_TIMEOUT_MS / 1000} seconds.`)),
        REQUEST_TIMEOUT_MS,
      );
    }),
  ]);
}

export const operationsApi = {
  health: (organizationId: string) =>
    bounded(
      platformApi.get<OperationalHealth>('/api/control-plane/health', headers(organizationId)),
      'Operational health request',
    ),
  previewReconciliation: (organizationId: string, limit: number) =>
    bounded(
      platformApi.post<ReconciliationResponse>(
        '/api/control-plane/reconciliation/artifacts/preview',
        { limit },
        headers(organizationId),
      ),
      'Reconciliation preview',
    ),
  runReconciliation: (organizationId: string, limit: number, correlationId: string) =>
    bounded(
      platformApi.post<ReconciliationResponse>(
        '/api/control-plane/reconciliation/artifacts/run',
        { limit, correlation_id: correlationId },
        headers(organizationId),
      ),
      'Reconciliation run',
    ),
};
