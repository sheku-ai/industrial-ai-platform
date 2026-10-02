import { platformApi, type JsonObject } from './platform-api';

export type OrganizationAccessUser = {
  membership_id: string;
  user_id: string;
  email: string;
  display_name?: string | null;
  identity_type: 'password' | 'unprovisioned';
  identity_status: string;
  membership_status: string;
  primary_role_id: string;
  roles: { assignment_id: string; role_id: string; status: string }[];
};

export type OrganizationAccessRole = {
  id: string;
  code: string;
  name: string;
  description?: string | null;
  status: string;
  is_system: boolean;
  protected: boolean;
  permission_ids: string[];
};

export type OrganizationAccessPermission = {
  id: string;
  resource: string;
  action: string;
  description?: string | null;
  key: string;
  delegable: boolean;
};

export type OrganizationAccessAssignment = {
  id: string;
  role_id: string;
  principal_type: string;
  principal_id: string;
  scope_type?: string | null;
  scope_id?: string | null;
  status: string;
  membership_id: string;
  display_name?: string | null;
  email: string;
  identity_type: string;
  identity_status: string;
  membership_status: string;
};

export type OrganizationAccessTechnicalPrincipal = {
  assignment_id: string;
  role_id: string;
  role_name: string;
  principal_type: string;
  principal_id: string;
  scope_type?: string | null;
  scope_id?: string | null;
  status: string;
};

export type OrganizationAccessPolicy = {
  id: string;
  code: string;
  name: string;
  effect: 'allow' | 'deny';
  rules: JsonObject;
  status: string;
};

export type OrganizationAccessRuntime = {
  runtime_name: string;
  runtime_status: string;
  organization_id: string;
  users: OrganizationAccessUser[];
  roles: OrganizationAccessRole[];
  permissions: OrganizationAccessPermission[];
  non_delegable_permissions: OrganizationAccessPermission[];
  policies: OrganizationAccessPolicy[];
  assignments: OrganizationAccessAssignment[];
  technical_principals: OrganizationAccessTechnicalPrincipal[];
  capabilities: {
    read: boolean;
    administer: boolean;
    email_delivery: boolean;
  };
  diagnostics: JsonObject;
  postgresql_source_of_truth: boolean;
};

export function getOrganizationAccessRuntime(): Promise<OrganizationAccessRuntime> {
  return platformApi.get<OrganizationAccessRuntime>('/api/security/organization-access/runtime');
}

export function createOrganizationUser(payload: {
  email: string;
  display_name?: string;
  role_id: string;
}): Promise<JsonObject> {
  return platformApi.post<JsonObject>('/api/security/organization-access/users', payload);
}

export function updateOrganizationMembership(membershipId: string, displayName: string): Promise<JsonObject> {
  return platformApi.patch<JsonObject>(
    `/api/security/organization-access/memberships/${membershipId}`,
    { display_name: displayName },
  );
}

export function setOrganizationMembershipStatus(
  membershipId: string,
  status: 'active' | 'disable' | 'removed',
): Promise<JsonObject> {
  if (status === 'removed') {
    return platformApi.delete<JsonObject>(`/api/security/organization-access/memberships/${membershipId}`);
  }
  const action = status === 'active' ? 'activate' : 'disable';
  return platformApi.post<JsonObject>(
    `/api/security/organization-access/memberships/${membershipId}/${action}`,
    {},
  );
}

export function createOrganizationRole(payload: {
  code: string;
  name: string;
  description?: string;
}): Promise<JsonObject> {
  return platformApi.post<JsonObject>('/api/security/organization-access/roles', payload);
}

export function updateOrganizationRole(
  roleId: string,
  payload: { name?: string; description?: string | null },
): Promise<JsonObject> {
  return platformApi.patch<JsonObject>(`/api/security/organization-access/roles/${roleId}`, payload);
}

export function duplicateOrganizationRole(
  roleId: string,
  payload: { code: string; name: string },
): Promise<JsonObject> {
  return platformApi.post<JsonObject>(
    `/api/security/organization-access/roles/${roleId}/duplicate`,
    payload,
  );
}

export function archiveOrganizationRole(roleId: string): Promise<JsonObject> {
  return platformApi.post<JsonObject>(`/api/security/organization-access/roles/${roleId}/archive`, {});
}

export function setOrganizationRoleStatus(
  roleId: string,
  status: 'active' | 'inactive',
): Promise<JsonObject> {
  return platformApi.post<JsonObject>(
    `/api/security/organization-access/roles/${roleId}/status/${status}`,
    {},
  );
}

export function deleteOrganizationRole(roleId: string): Promise<JsonObject> {
  return platformApi.delete<JsonObject>(`/api/security/organization-access/roles/${roleId}`);
}

export function setOrganizationRolePermission(
  roleId: string,
  permissionId: string,
  assigned: boolean,
): Promise<JsonObject> {
  const path = `/api/security/organization-access/roles/${roleId}/permissions/${permissionId}`;
  return assigned ? platformApi.put<JsonObject>(path, {}) : platformApi.delete<JsonObject>(path);
}

export function createOrganizationAssignment(
  membershipId: string,
  roleId: string,
): Promise<JsonObject> {
  return platformApi.post<JsonObject>('/api/security/organization-access/assignments', {
    membership_id: membershipId,
    role_id: roleId,
  });
}

export function removeOrganizationAssignment(assignmentId: string): Promise<JsonObject> {
  return platformApi.delete<JsonObject>(`/api/security/organization-access/assignments/${assignmentId}`);
}

export function createOrganizationPolicy(payload: {
  code: string;
  name: string;
  effect: 'allow' | 'deny';
  rules: JsonObject;
}): Promise<JsonObject> {
  return platformApi.post<JsonObject>('/api/security/organization-access/policies', payload);
}

export function updateOrganizationPolicy(
  policyId: string,
  payload: { name?: string; effect?: 'allow' | 'deny'; rules?: JsonObject },
): Promise<JsonObject> {
  return platformApi.patch<JsonObject>(`/api/security/organization-access/policies/${policyId}`, payload);
}

export function setOrganizationPolicyStatus(
  policyId: string,
  status: 'active' | 'inactive' | 'archived',
): Promise<JsonObject> {
  return platformApi.post<JsonObject>(
    `/api/security/organization-access/policies/${policyId}/${status}`,
    {},
  );
}
