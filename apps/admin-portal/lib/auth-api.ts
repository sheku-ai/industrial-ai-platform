'use client';

import { httpRequest, invalidateCsrfToken } from './http-client';

export type AuthUser = {
  id: string;
  username: string;
  email: string;
  display_name: string | null;
  status: string;
  must_change_password: boolean;
};

export type AuthMembership = {
  id: string;
  organization_id: string;
  role_id: string;
  status: string;
};

export type AuthSession = {
  id: string;
  created_at: string;
  last_activity_at: string;
  idle_expires_at: string;
  absolute_expires_at: string;
  remember_me: boolean;
};

export type ManagedAuthSession = AuthSession & {
  current: boolean;
  revoked_at: string | null;
  revocation_reason: string | null;
  client_ip: string | null;
  user_agent: string | null;
  status: string;
};

export type SessionStatusFilter = 'all' | 'active' | 'expired' | 'revoked';
export type SessionPage = {
  sessions: ManagedAuthSession[];
  total: number;
  offset: number;
  limit: number;
  status_filter: SessionStatusFilter;
};

export type AuthPrincipal = {
  user: AuthUser;
  session: AuthSession;
  memberships: AuthMembership[];
};

export type LoginResponse = AuthPrincipal & {
  authenticated: true;
};

export type PasswordChangedResponse = {
  password_changed: true;
  all_sessions_revoked: true;
  reauthentication_required: true;
};

export const authApi = {
  sessionPolicy: () => httpRequest<{ remember_me_enabled: boolean }>(
    '/auth/session-policy',
    { method: 'GET' },
    { csrf: false, emitSessionExpired: false },
  ),
  async login(email: string, password: string, rememberMe = false): Promise<LoginResponse> {
    invalidateCsrfToken();
    const principal = await httpRequest<LoginResponse>(
      '/auth/login',
      { method: 'POST', body: JSON.stringify({ email, password, remember_me: rememberMe }) },
      { csrf: false, emitSessionExpired: false },
    );
    invalidateCsrfToken();
    return principal;
  },
  me: () => httpRequest<AuthPrincipal>(
    '/auth/me',
    { method: 'GET' },
    { emitSessionExpired: false },
  ),
  async logout(): Promise<void> {
    try {
      await httpRequest<void>(
        '/auth/logout',
        { method: 'POST' },
        { emitSessionExpired: false, expectedStatuses: [204] },
      );
    } finally {
      invalidateCsrfToken();
    }
  },
  async changePassword(currentPassword: string, newPassword: string): Promise<PasswordChangedResponse> {
    invalidateCsrfToken();
    try {
      return await httpRequest<PasswordChangedResponse>(
        '/auth/change-password',
        {
          method: 'POST',
          body: JSON.stringify({
            current_password: currentPassword,
            new_password: newPassword,
          }),
        },
        { emitSessionExpired: false },
      );
    } finally {
      invalidateCsrfToken();
    }
  },
  sessions: (status: SessionStatusFilter, offset: number, limit: number) => httpRequest<SessionPage>(
    `/auth/sessions?status=${status}&offset=${offset}&limit=${limit}`,
    { method: 'GET' },
  ),
  revokeSession: (sessionId: string) => httpRequest<void>(
    `/auth/sessions/${sessionId}`,
    { method: 'DELETE' },
    { expectedStatuses: [204] },
  ),
  revokeOtherSessions: () => httpRequest<void>(
    '/auth/sessions/revoke-others',
    { method: 'POST' },
    { expectedStatuses: [204] },
  ),
};
