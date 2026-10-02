import { platformApi } from './platform-api';

const PLATFORM_HEADERS = { 'X-Authorization-Scope': 'platform' };

export type GlobalRolePermission = {
  id: string;
  resource: string;
  action: string;
  key: string;
  description?: string | null;
};

export type GlobalRole = {
  role_id: string;
  code: string;
  name: string;
  description?: string | null;
  scope: 'platform';
  status: string;
  is_system: boolean;
  configurable: boolean;
  permission_keys: string[];
  outcome?: 'created' | 'idempotent' | 'updated' | null;
};

export type GlobalRoleSpecification = {
  code: string;
  name: string;
  description?: string;
  permission_keys: string[];
};

export function listGlobalRoles(): Promise<GlobalRole[]> {
  return platformApi.get<GlobalRole[]>(
    '/api/security/management/global-roles',
    PLATFORM_HEADERS,
  );
}

export function listGlobalRolePermissions(): Promise<GlobalRolePermission[]> {
  return platformApi.get<GlobalRolePermission[]>(
    '/api/security/management/permissions?limit=500',
    PLATFORM_HEADERS,
  );
}

export function reconcileGlobalRole(payload: GlobalRoleSpecification): Promise<GlobalRole> {
  return platformApi.post<GlobalRole>(
    '/api/security/management/global-roles/reconcile',
    payload,
    PLATFORM_HEADERS,
  );
}

export function setGlobalRoleStatus(code: string, active: boolean): Promise<GlobalRole> {
  const action = active ? 'activate' : 'deactivate';
  return platformApi.post<GlobalRole>(
    `/api/security/management/global-roles/${encodeURIComponent(code)}/${action}`,
    {},
    PLATFORM_HEADERS,
  );
}
