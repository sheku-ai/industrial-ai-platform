import type { SessionPage, SessionStatusFilter } from './auth-api';
import { platformApi } from './platform-api';

const PLATFORM_HEADERS = { 'X-Authorization-Scope': 'platform' };

export type SessionPolicy = {
  id: string;
  scope: 'platform';
  status: 'active';
  version: number;
  idle_timeout_seconds: number;
  absolute_timeout_seconds: number;
  max_concurrent_sessions: number;
  activity_write_interval_seconds: number;
  remember_me_enabled: boolean;
  remember_idle_timeout_seconds: number;
  remember_absolute_timeout_seconds: number;
  retention_days: number;
  updated_at: string;
  updated_by: string | null;
};

export type PolicyUpdate = Omit<SessionPolicy, 'id' | 'scope' | 'status' | 'version' | 'updated_at' | 'updated_by'> & {
  application_mode: 'new_sessions_only' | 'restrict_existing';
};

export const sessionManagementApi = {
  policy: () => platformApi.get<SessionPolicy>('/api/platform/security/session-policy', PLATFORM_HEADERS),
  updatePolicy: (payload: PolicyUpdate) => platformApi.put<SessionPolicy>('/api/platform/security/session-policy', payload, PLATFORM_HEADERS),
  userSessions: (userId: string, status: SessionStatusFilter, offset: number, limit: number) => platformApi.get<SessionPage & { user_id: string }>(`/api/platform/security/users/${userId}/sessions?status=${status}&offset=${offset}&limit=${limit}`, PLATFORM_HEADERS),
  revoke: (userId: string, sessionId: string) => platformApi.delete(`/api/platform/security/users/${userId}/sessions/${sessionId}`, PLATFORM_HEADERS),
  revokeAll: (userId: string) => platformApi.post(`/api/platform/security/users/${userId}/sessions/revoke-all`, {}, PLATFORM_HEADERS),
};
