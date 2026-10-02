import { platformApi } from './platform-api';
import {
  normalizeGlobalManagedUser,
  normalizeGlobalUserMutation,
  type GlobalUserMutation,
  type GlobalUserRuntime,
} from './global-user-contract';

export type {
  GlobalManagedUser,
  GlobalUserMutation,
  GlobalUserRuntime,
  UserMembershipSummary,
  UserRoleSummary,
} from './global-user-contract';
export { normalizeGlobalManagedUser, normalizeGlobalUserMutation } from './global-user-contract';

const PLATFORM_HEADERS = { 'X-Authorization-Scope': 'platform' };

async function normalizedMutation(operation: Promise<GlobalUserMutation>): Promise<GlobalUserMutation> {
  return normalizeGlobalUserMutation(await operation);
}

export const globalUserApi = {
  runtime: async () => {
    const runtime = await platformApi.get<GlobalUserRuntime>(
      '/api/security/management/global-users/runtime',
      PLATFORM_HEADERS,
    );
    return { ...runtime, users: runtime.users.map(normalizeGlobalManagedUser) };
  },
  create: (payload: { username: string; display_name: string; email: string; temporary_password: string }) => normalizedMutation(platformApi.post<GlobalUserMutation>('/api/security/management/global-users', payload, PLATFORM_HEADERS)),
  update: (userId: string, payload: { username?: string; display_name?: string; email?: string }) => normalizedMutation(platformApi.patch<GlobalUserMutation>(`/api/security/management/global-users/${userId}`, payload, PLATFORM_HEADERS)),
  resetPassword: (userId: string, temporaryPassword: string) => normalizedMutation(platformApi.post<GlobalUserMutation>(`/api/security/management/global-users/${userId}/reset-password`, { temporary_password: temporaryPassword }, PLATFORM_HEADERS)),
  revokeSessions: (userId: string) => normalizedMutation(platformApi.post<GlobalUserMutation>(`/api/security/management/global-users/${userId}/revoke-sessions`, {}, PLATFORM_HEADERS)),
  setStatus: (userId: string, active: boolean) => normalizedMutation(platformApi.post<GlobalUserMutation>(`/api/security/management/global-users/${userId}/${active ? 'activate' : 'deactivate'}`, {}, PLATFORM_HEADERS)),
  setGlobalRole: (userId: string, roleId: string, active: boolean) => active
    ? normalizedMutation(platformApi.put<GlobalUserMutation>(`/api/security/management/global-users/${userId}/global-roles/${roleId}`, {}, PLATFORM_HEADERS))
    : normalizedMutation(platformApi.delete<GlobalUserMutation>(`/api/security/management/global-users/${userId}/global-roles/${roleId}`, PLATFORM_HEADERS)),
  setMembership: (userId: string, organizationId: string, roleId: string | null) => roleId
    ? normalizedMutation(platformApi.put<GlobalUserMutation>(`/api/security/management/global-users/${userId}/memberships/${organizationId}`, { role_id: roleId }, PLATFORM_HEADERS))
    : normalizedMutation(platformApi.delete<GlobalUserMutation>(`/api/security/management/global-users/${userId}/memberships/${organizationId}`, PLATFORM_HEADERS)),
  setOrganizationRole: (userId: string, organizationId: string, roleId: string, active: boolean) => active
    ? normalizedMutation(platformApi.put<GlobalUserMutation>(`/api/security/management/global-users/${userId}/organizations/${organizationId}/roles/${roleId}`, {}, PLATFORM_HEADERS))
    : normalizedMutation(platformApi.delete<GlobalUserMutation>(`/api/security/management/global-users/${userId}/organizations/${organizationId}/roles/${roleId}`, PLATFORM_HEADERS)),
  delete: (userId: string) => normalizedMutation(platformApi.delete<GlobalUserMutation>(`/api/security/management/global-users/${userId}`, PLATFORM_HEADERS)),
};
