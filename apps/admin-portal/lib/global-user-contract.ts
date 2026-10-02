export type UserRoleSummary = {
  role_id: string;
  name: string | null;
  code: string | null;
  status: string;
  scope: 'platform' | 'organization';
  is_system: boolean | null;
  permission_keys: string[];
  available: boolean;
  inconsistency: string | null;
};

export type UserMembershipSummary = {
  membership_id: string;
  organization_id: string;
  organization_name: string;
  roles: UserRoleSummary[];
};

export type GlobalManagedUser = {
  user_id: string;
  username: string;
  display_name: string | null;
  email: string;
  status: string;
  must_change_password: boolean;
  active_sessions: number;
  global_roles: UserRoleSummary[];
  memberships: UserMembershipSummary[];
};

export type GlobalUserRuntime = {
  users: GlobalManagedUser[];
  organizations: { organization_id: string; name: string }[];
  global_roles: UserRoleSummary[];
  organization_roles: (UserRoleSummary & { organization_id: string })[];
  capabilities: { read: boolean; administer: boolean };
  postgresql_source_of_truth: true;
};

export type GlobalUserMutation = {
  operation: string;
  outcome: string;
  user: GlobalManagedUser | null;
};

function requiredIdentityField(value: unknown, field: 'username' | 'email'): string {
  if (typeof value !== 'string' || !value.trim()) {
    throw new Error(`The global identity response is missing ${field}.`);
  }
  return value;
}

export function normalizeGlobalManagedUser(user: GlobalManagedUser): GlobalManagedUser {
  return {
    ...user,
    username: requiredIdentityField(user.username, 'username'),
    email: requiredIdentityField(user.email, 'email'),
  };
}

export function normalizeGlobalUserMutation(result: GlobalUserMutation): GlobalUserMutation {
  return {
    ...result,
    user: result.user ? normalizeGlobalManagedUser(result.user) : null,
  };
}
