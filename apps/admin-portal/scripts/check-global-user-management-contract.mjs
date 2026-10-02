import fs from 'node:fs';

const files = {
  boundary: fs.readFileSync(new URL('../components/auth/AuthBoundary.tsx', import.meta.url), 'utf8'),
  manager: fs.readFileSync(new URL('../components/security/GlobalUserManager.tsx', import.meta.url), 'utf8'),
  profileEditor: fs.readFileSync(new URL('../components/security/GlobalUserProfileEditor.tsx', import.meta.url), 'utf8'),
  gate: fs.readFileSync(new URL('../components/security/GlobalSecurityAdministration.tsx', import.meta.url), 'utf8'),
  api: fs.readFileSync(new URL('../lib/global-user-management-api.ts', import.meta.url), 'utf8'),
  contract: fs.readFileSync(new URL('../lib/global-user-contract.ts', import.meta.url), 'utf8'),
  editor: fs.readFileSync(new URL('../lib/global-user-editor.ts', import.meta.url), 'utf8'),
  backendService: fs.readFileSync(new URL('../../api/app/services/global_user_management.py', import.meta.url), 'utf8'),
  backendSchema: fs.readFileSync(new URL('../../api/app/schemas/security_management.py', import.meta.url), 'utf8'),
  en: fs.readFileSync(new URL('../i18n/en.json', import.meta.url), 'utf8'),
  es: fs.readFileSync(new URL('../i18n/es.json', import.meta.url), 'utf8'),
};

const checks = {
  forced_password_boundary: files.boundary.includes('must_change_password') && files.boundary.includes('ForcedPasswordChange'),
  single_authorization_gate: files.gate.includes('data-global-security-access="required"') && files.gate.includes('PlatformApiError'),
  governed_user_actions: ['resetPassword', 'revokeSessions', 'setGlobalRole', 'setMembership', 'delete'].every((value) => files.manager.includes(value)),
  backend_maps_persisted_identity_fields:
    files.backendService.includes('"username": user.username')
    && files.backendService.includes('"email": user.email_display'),
  serialized_contract_rejects_empty_identity_fields:
    files.backendSchema.includes('username: str = Field(min_length=1)')
    && files.backendSchema.includes('email: str = Field(min_length=1)'),
  client_preserves_authoritative_fields:
    files.contract.includes("username: requiredIdentityField(user.username, 'username')")
    && files.contract.includes("email: requiredIdentityField(user.email, 'email')")
    && files.api.includes('runtime.users.map(normalizeGlobalManagedUser)'),
  mutation_responses_are_normalized:
    files.api.includes('normalizedMutation(platformApi.post<GlobalUserMutation>')
    && files.api.includes('normalizedMutation(platformApi.patch<GlobalUserMutation>')
    && files.contract.includes('user: result.user ? normalizeGlobalManagedUser(result.user) : null'),
  authoritative_profile_hydration:
    files.editor.includes('export function createGlobalUserDraft')
    && files.editor.includes('username: user.username')
    && files.editor.includes('display_name: user.display_name')
    && files.editor.includes('email: user.email')
    && files.profileEditor.includes("type: 'authoritative'"),
  single_authoritative_transition:
    files.editor.includes('export function reduceGlobalUserEditor')
    && files.profileEditor.includes('useReducer(')
    && !files.manager.includes('setProfileDraft'),
  controlled_profile_draft: ['value={draft.username}', 'value={draft.display_name}', 'value={draft.email}'].every((value) => files.profileEditor.includes(value)),
  explicit_view_before_edit:
    files.profileEditor.includes('data-global-user-profile-mode="view"')
    && files.profileEditor.includes("type: 'begin_edit'")
    && files.editor.includes("mode: 'view' | 'edit'"),
  unchanged_or_invalid_profile_disabled: files.profileEditor.includes('!changed || !valid') && files.editor.includes("draft.username.trim()") && files.editor.includes("draft.email.trim()"),
  selection_reinitializes_draft:
    files.manager.includes('key={selected.user_id}')
    && files.editor.includes("action.type === 'select'"),
  creation_and_profile_edit_are_mutually_exclusive:
    files.manager.includes('selected && !creationOpen')
    && files.manager.includes('creationOpen ? <form')
    && files.editor.includes('profileEditForm: !creationOpen'),
  stale_runtime_response_ignored: files.gate.includes('refreshSequence') && files.gate.includes('sequence !== refreshSequence.current'),
  update_contains_only_changed_profile_fields: files.editor.includes('changedProfileFields') && !files.editor.includes('global_roles') && !files.editor.includes('memberships'),
  assigned_role_inconsistency_visible: files.manager.includes('assignedRoleUnavailable') && files.manager.includes('!role.available'),
  platform_scope: files.api.includes("'X-Authorization-Scope': 'platform'"),
  no_secret_response_contract: !files.api.includes('password_hash') && !files.api.includes('token_hash'),
  localized: files.en.includes('"globalUsers"') && files.es.includes('"globalUsers"'),
};

const passed = Object.values(checks).every(Boolean);
console.log(JSON.stringify({ ...checks, passed }, null, 2));
if (!passed) process.exitCode = 1;
