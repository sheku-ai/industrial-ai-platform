'use client';

import { platformApi } from './platform-api';

export type WorkerDesiredState = 'active' | 'paused' | 'draining' | 'disabled';

export type RuntimeWorker = {
  id: string;
  worker_key: string;
  instance_id: string;
  worker_type: string;
  desired_state: WorkerDesiredState;
  observed_state: string;
  capabilities: string[];
  heartbeat_at?: string | null;
  last_error_code?: string | null;
  last_error_message?: string | null;
  heartbeat_stale: boolean;
  accepting_work: boolean;
  ready: boolean;
  metrics: Record<string, unknown>;
};

export type RuntimeWorkerSummary = {
  calculated_at: string;
  total_workers: number;
  active_desired: number;
  paused_desired: number;
  draining_desired: number;
  disabled_desired: number;
  ready_workers: number;
  accepting_work: number;
  stale_workers: number;
  failed_workers: number;
  offline_workers: number;
  busy_workers: number;
  degraded_workers: number;
  available_capacity_ratio: number;
};

export type RuntimeWorkerHistory = {
  id: string;
  action: string;
  before_state: Record<string, unknown>;
  after_state: Record<string, unknown>;
  actor_type?: string | null;
  actor_id?: string | null;
  created_at: string;
};

function headers(): HeadersInit {
  return {
    'X-Authorization-Scope': 'platform',
  };
}

export const runtimeWorkersApi = {
  list: () => platformApi.get<RuntimeWorker[]>('/api/control-plane/workers', headers()),
  summary: () => platformApi.get<RuntimeWorkerSummary>('/api/control-plane/workers/summary', headers()),
  history: (workerKey: string) =>
    platformApi.get<RuntimeWorkerHistory[]>(
      `/api/control-plane/workers/${encodeURIComponent(workerKey)}/history?limit=20`,
      headers(),
    ),
  setDesiredState: (workerKey: string, desiredState: WorkerDesiredState) =>
    platformApi.put<RuntimeWorker>(
      `/api/control-plane/workers/${encodeURIComponent(workerKey)}/desired-state`,
      { desired_state: desiredState },
      headers(),
    ),
};
