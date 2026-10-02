'use client';

import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useI18n } from '../../i18n/I18nProvider';
import { LocalizedText } from '../layout/LocalizedText';
import { ActionConfirmationDialog } from '../layout/ActionConfirmationDialog';
import {
  archiveOrganizationRole,
  createOrganizationAssignment,
  createOrganizationPolicy,
  createOrganizationRole,
  createOrganizationUser,
  deleteOrganizationRole,
  duplicateOrganizationRole,
  getOrganizationAccessRuntime,
  removeOrganizationAssignment,
  setOrganizationMembershipStatus,
  setOrganizationPolicyStatus,
  setOrganizationRolePermission,
  setOrganizationRoleStatus,
  updateOrganizationMembership,
  updateOrganizationPolicy,
  updateOrganizationRole,
  type OrganizationAccessPolicy,
  type OrganizationAccessRole,
  type OrganizationAccessRuntime,
} from '../../lib/organization-access-api';
import { localizedApiError, localizedProductLabel } from '../../lib/presentation';

type AccessView = 'users' | 'roles' | 'permissions' | 'assignments' | 'policies';

const ACCESS_LABEL_KEYS: Record<string, string> = {
  inactive: 'access.statusInactive',
  suspended: 'access.statusSuspended',
  removed: 'access.statusRemoved',
  archived: 'access.statusArchived',
  unprovisioned: 'access.identityUnprovisioned',
  password: 'access.identityPassword',
  allow: 'access.allow',
  deny: 'access.deny',
  active: 'status.active',
  read: 'access.permissionActionRead',
  administer: 'access.permissionActionAdminister',
  execute: 'access.permissionActionExecute',
};

const ACCESS_RESOURCE_LABEL_KEYS: Record<string, string> = {
  'ai.configuration': 'access.resources.aiConfiguration',
  'ai.models': 'access.resources.aiModels',
  'ai.providers': 'access.resources.aiProviders',
  'ai.validation': 'access.resources.aiValidation',
  'control_plane.health': 'access.resources.operationalHealth',
  'control_plane.reconciliation': 'access.resources.reconciliation',
  'control_plane.scheduler': 'access.resources.scheduler',
  'control_plane.workers': 'access.resources.workers',
  document_configuration: 'access.resources.documentConfiguration',
  documents: 'access.resources.documents',
  knowledge_collections: 'access.resources.knowledgeCollections',
  'organization.dashboard': 'access.resources.organizationDashboard',
  'organization.reporting': 'access.resources.organizationReporting',
  'organization.security': 'access.resources.organizationSecurity',
  'platform.assistants': 'access.resources.assistants',
  reference_tenant: 'access.resources.referenceTenant',
};

const ACCESS_ROLE_DESCRIPTION_KEYS: Record<string, string> = {
  'reference-administrator': 'access.roleDescriptions.referenceAdministrator',
  'reference-reviewer': 'access.roleDescriptions.referenceReviewer',
};

type ConfirmationRequest = {
  confirmLabel: string;
  description: string;
  title: string;
  action: () => Promise<boolean>;
};

function accessLabel(
  value: unknown,
  translate: (key: string) => string,
): string {
  const key = ACCESS_LABEL_KEYS[String(value ?? '').trim().toLowerCase()];
  return key ? translate(key) : localizedProductLabel(value, translate);
}

function accessResourceLabel(value: string, translate: (key: string) => string): string {
  const key = ACCESS_RESOURCE_LABEL_KEYS[value];
  return key ? translate(key) : translate('dynamic.detailsAvailable');
}

function permissionDescription(resource: string, action: string, translate: (key: string, values?: Record<string, string | number | boolean | null | undefined>) => string): string {
  const actionKey: Record<string, string> = {
    administer: 'access.permissionDescriptionAdminister',
    execute: 'access.permissionDescriptionExecute',
    read: 'access.permissionDescriptionRead',
  };
  const key = actionKey[action];
  return key ? translate(key, { resource: accessResourceLabel(resource, translate) }) : translate('dynamic.detailsAvailable');
}

function roleLabel(runtime: OrganizationAccessRuntime, roleId: string, fallback: string): string {
  return runtime.roles.find((role) => role.id === roleId)?.name || fallback;
}

function administrativePermissionCount(
  runtime: OrganizationAccessRuntime,
  role: OrganizationAccessRole,
): number {
  const permissions = [...runtime.permissions, ...runtime.non_delegable_permissions];
  return permissions.filter((permission) => (
    role.permission_ids.includes(permission.id)
    && permission.action === 'administer'
  )).length;
}

function roleSelectionHasGuidance(
  runtime: OrganizationAccessRuntime,
  role: OrganizationAccessRole | undefined,
): boolean {
  return Boolean(
    role
    && (
      administrativePermissionCount(runtime, role) > 0
      || role.protected
      || role.description
    )
  );
}

function RoleSelectionGuidance({
  id,
  role,
  runtime,
}: {
  id: string;
  role: OrganizationAccessRole | undefined;
  runtime: OrganizationAccessRuntime;
}) {
  const { t } = useI18n();
  if (!role) return null;
  const administrativePermissions = administrativePermissionCount(runtime, role);
  if (administrativePermissions > 0) {
    return (
      <p className="access-role-warning" id={id} role="note">
        {t('access.administrativeRoleWarning', { count: administrativePermissions })}
      </p>
    );
  }
  if (role.protected) {
    return (
      <p className="access-role-warning" id={id} role="note">
        {t('access.protectedRoleSelectionWarning')}
      </p>
    );
  }
  const knownDescription = ACCESS_ROLE_DESCRIPTION_KEYS[role.code];
  return role.description ? <p className="access-field-help" id={id}>{knownDescription ? t(knownDescription) : role.description}</p> : null;
}

export function OrganizationAccessManager() {
  const { t } = useI18n();
  const [runtime, setRuntime] = useState<OrganizationAccessRuntime | null>(null);
  const [view, setView] = useState<AccessView>('users');
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const mutationInFlight = useRef(false);
  const [confirmation, setConfirmation] = useState<ConfirmationRequest | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRuntime(await getOrganizationAccessRuntime());
    } catch (cause) {
      setError(localizedApiError(cause, t, 'feedback.securityRuntimeUnavailable'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const mutate = useCallback(async (operation: () => Promise<unknown>, successMessage: string) => {
    if (mutationInFlight.current) return false;
    mutationInFlight.current = true;
    setPending(true);
    setError(null);
    setNotice(null);
    try {
      await operation();
      setNotice(successMessage);
      setRuntime(await getOrganizationAccessRuntime());
      return true;
    } catch (cause) {
      setError(localizedApiError(cause, t, 'access.operationFailed'));
      return false;
    } finally {
      mutationInFlight.current = false;
      setPending(false);
    }
  }, [t]);

  const requestConfirmation = useCallback((request: ConfirmationRequest) => setConfirmation(request), []);

  const runConfirmedAction = async () => {
    if (!confirmation || mutationInFlight.current) return;
    await confirmation.action();
    setConfirmation(null);
  };

  if (loading && !runtime) {
    return <section className="card" role="status"><h2>{t('access.loading')}</h2></section>;
  }
  if (!runtime) {
    return (
      <section className="card">
        <h2>{t('access.unavailable')}</h2>
        <p>{error}</p>
        <button className="button secondary" onClick={() => void refresh()} type="button">{t('common.actions.retry')}</button>
      </section>
    );
  }

  const labels: Record<AccessView, string> = {
    users: t('access.users'),
    roles: t('copy.roles_47dcc27d'),
    permissions: t('copy.permissions_d06d5557'),
    assignments: t('copy.assignments_057d58c7'),
    policies: t('copy.policies_8d611849'),
  };

  return (
    <div className="organization-access-manager">
      <section className="table-card">
        <div className="section-header">
          <span className="eyebrow">{t('access.organizationAccess')}</span>
          <h2>{t('pages.security.title')}</h2>
          <p>{t('access.description')}</p>
        </div>
        <div aria-label={t('access.sections')} className="workspace-tabs" role="tablist">
          {(Object.keys(labels) as AccessView[]).map((item) => (
            <button
              aria-selected={view === item}
              className={view === item ? 'is-active' : ''}
              key={item}
              onClick={() => setView(item)}
              role="tab"
              type="button"
            >
              {labels[item]}
            </button>
          ))}
        </div>
        {!runtime.capabilities.administer ? <p className="context-message">{t('access.readOnly')}</p> : null}
        {!runtime.capabilities.email_delivery ? <p className="context-message">{t('access.noEmailDelivery')}</p> : null}
        {notice ? <p className="form-success" role="status">{notice}</p> : null}
        {error ? <p className="form-error" role="alert">{error}</p> : null}
      </section>
      {view === 'users' ? <UsersView runtime={runtime} disabled={pending || !runtime.capabilities.administer} mutate={mutate} requestConfirmation={requestConfirmation} /> : null}
      {view === 'roles' ? <RolesView runtime={runtime} disabled={pending || !runtime.capabilities.administer} mutate={mutate} requestConfirmation={requestConfirmation} /> : null}
      {view === 'permissions' ? <PermissionsView runtime={runtime} disabled={pending || !runtime.capabilities.administer} mutate={mutate} requestConfirmation={requestConfirmation} /> : null}
      {view === 'assignments' ? <AssignmentsView runtime={runtime} disabled={pending || !runtime.capabilities.administer} mutate={mutate} requestConfirmation={requestConfirmation} /> : null}
      {view === 'policies' ? <PoliciesView runtime={runtime} disabled={pending || !runtime.capabilities.administer} mutate={mutate} requestConfirmation={requestConfirmation} /> : null}
      <ActionConfirmationDialog cancelLabel={t('common.actions.cancel')} confirmLabel={confirmation?.confirmLabel ?? t('common.actions.confirm')} description={confirmation?.description ?? ''} onCancel={() => { if (!pending) setConfirmation(null); }} onConfirm={() => void runConfirmedAction()} open={Boolean(confirmation)} pending={pending} title={confirmation?.title ?? ''} />
    </div>
  );
}

type ViewProps = {
  runtime: OrganizationAccessRuntime;
  disabled: boolean;
  mutate: (operation: () => Promise<unknown>, successMessage: string) => Promise<boolean>;
  requestConfirmation: (request: ConfirmationRequest) => void;
};

function UsersView({ runtime, disabled, mutate, requestConfirmation }: ViewProps) {
  const { t } = useI18n();
  const activeRoles = runtime.roles.filter((role) => role.status === 'active');
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [roleId, setRoleId] = useState('');
  const [editingMembershipId, setEditingMembershipId] = useState('');
  const [editingName, setEditingName] = useState('');
  const selectedRole = activeRoles.find((role) => role.id === roleId);
  const selectedRoleHasGuidance = roleSelectionHasGuidance(runtime, selectedRole);

  function resetCreateForm() {
    setEmail('');
    setDisplayName('');
    setRoleId('');
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!selectedRole) return;
    const saved = await mutate(
      () => createOrganizationUser({ email, display_name: displayName || undefined, role_id: roleId }),
      t('access.userAdded'),
    );
    if (saved) resetCreateForm();
  }

  return (
    <section className="table-card">
      <h2>{t('access.users')}</h2>
      <p className="access-operation-help" id="identity-registration-help">
        {t('access.identityRegistrationHelp')}
      </p>
      <form className="access-form-grid" onSubmit={(event) => void submit(event)}>
        <label className="access-form-field" htmlFor="access-identity-email">
          <span className="field-label">{t('access.email')}</span>
          <input autoComplete="off" className="field-control" disabled={disabled} id="access-identity-email" onChange={(event) => setEmail(event.target.value)} required type="email" value={email} />
        </label>
        <label className="access-form-field" htmlFor="access-identity-display-name">
          <span className="field-label">{t('access.displayName')}</span>
          <input className="field-control" disabled={disabled} id="access-identity-display-name" onChange={(event) => setDisplayName(event.target.value)} value={displayName} />
        </label>
        <label className="access-form-field" htmlFor="access-identity-role">
          <span className="field-label">{t('copy.role_c3f104d1')}</span>
          <select
            aria-describedby={selectedRoleHasGuidance ? 'identity-registration-help access-identity-role-guidance' : 'identity-registration-help'}
            className="field-control"
            disabled={disabled || activeRoles.length === 0}
            id="access-identity-role"
            onChange={(event) => setRoleId(event.target.value)}
            required
            value={roleId}
          >
            <option value="">{t('access.selectRole')}</option>
            {activeRoles.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}
          </select>
          {activeRoles.length === 0 ? <span className="access-field-help">{t('access.noActiveRoles')}</span> : null}
        </label>
        <RoleSelectionGuidance id="access-identity-role-guidance" role={selectedRole} runtime={runtime} />
        <div className="access-form-actions">
          <button className="button" disabled={disabled || !email.trim() || !selectedRole} type="submit">{t('access.addIdentity')}</button>
          <button className="button secondary" disabled={disabled || (!email && !displayName && !roleId)} onClick={resetCreateForm} type="button">{t('common.actions.cancel')}</button>
        </div>
      </form>
      <div className="table-scroll">
        <table>
          <thead><tr><th>{t('access.user')}</th><th>{t('access.email')}</th><th>{t('copy.roles_47dcc27d')}</th><th>{t('common.status')}</th><th>{t('common.actionColumn')}</th></tr></thead>
          <tbody>
            {runtime.users.length === 0 ? <tr><td className="table-empty" colSpan={5}>{t('access.noUsers')}</td></tr> : null}
            {runtime.users.map((user) => (
              <tr key={user.membership_id}>
                <td>
                  {editingMembershipId === user.membership_id ? (
                    <form className="inline-edit" onSubmit={(event) => {
                      event.preventDefault();
                      void mutate(
                        () => updateOrganizationMembership(user.membership_id, editingName),
                        t('access.userUpdated'),
                      ).then((saved) => {
                        if (saved) {
                          setEditingMembershipId('');
                          setEditingName('');
                        }
                      });
                    }}>
                      <input aria-label={t('access.displayName')} className="field-control" disabled={disabled} onChange={(event) => setEditingName(event.target.value)} required value={editingName} />
                      <button className="button secondary" disabled={disabled || !editingName.trim()} type="submit">{t('common.actions.save')}</button>
                      <button className="button secondary" disabled={disabled} onClick={() => { setEditingMembershipId(''); setEditingName(''); }} type="button">{t('common.actions.cancel')}</button>
                    </form>
                  ) : user.display_name || t('common.notAvailable')}
                </td>
                <td>{user.email}<small className="table-secondary">{accessLabel(user.identity_type, t)}</small></td>
                <td>{user.roles.filter((assignment) => assignment.status === 'active').map((assignment) => roleLabel(runtime, assignment.role_id, t('access.unknownRole'))).join(', ') || t('common.none')}</td>
                <td>{accessLabel(user.membership_status, t)}</td>
                <td>
                  <div className="access-table-actions">
                    <button className="button secondary" disabled={disabled} onClick={() => { setEditingMembershipId(user.membership_id); setEditingName(user.display_name || ''); }} type="button">{t('access.editName')}</button>
                    {user.membership_status === 'active' ? <button className="button danger administrative-destructive-action" disabled={disabled} onClick={() => requestConfirmation({ title: t('confirmation.disableMembershipTitle', { name: user.display_name || user.email }), description: t('confirmation.disableMembershipEffect'), confirmLabel: t('access.disable'), action: () => mutate(() => setOrganizationMembershipStatus(user.membership_id, 'disable'), t('access.membershipDisabled')) })} type="button">{t('access.disable')}</button> : <button className="button secondary" disabled={disabled} onClick={() => void mutate(() => setOrganizationMembershipStatus(user.membership_id, 'active'), t('access.membershipActivated'))} type="button">{t('access.activate')}</button>}
                    {user.membership_status !== 'removed' ? <button className="button danger administrative-destructive-action" disabled={disabled} onClick={() => requestConfirmation({ title: t('confirmation.removeMembershipTitle', { name: user.display_name || user.email }), description: t('confirmation.removeMembershipEffect'), confirmLabel: t('common.actions.remove'), action: () => mutate(() => setOrganizationMembershipStatus(user.membership_id, 'removed'), t('access.membershipRemoved')) })} type="button">{t('common.actions.remove')}</button> : null}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function RolesView({ runtime, disabled, mutate, requestConfirmation }: ViewProps) {
  const { t } = useI18n();
  const [selectedId, setSelectedId] = useState('');
  const selected = runtime.roles.find((role) => role.id === selectedId);
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');

  function selectRole(role: OrganizationAccessRole) {
    setSelectedId(role.id);
    setCode('');
    setName(role.name);
    setDescription(role.description || '');
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (selected) {
      await mutate(() => updateOrganizationRole(selected.id, { name, description }), t('access.roleUpdated'));
    } else {
      const saved = await mutate(() => createOrganizationRole({ code, name, description }), t('access.roleCreated'));
      if (saved) {
        setCode('');
        setName('');
        setDescription('');
      }
    }
  }

  return (
    <section className="table-card">
      <h2>{t('copy.roles_47dcc27d')}</h2>
      <form className="access-form-grid" onSubmit={(event) => void submit(event)}>
        {!selected ? (
          <label className="access-form-field" htmlFor="access-role-code">
            <span className="field-label">{t('common.code')}</span>
            <input className="field-control" disabled={disabled} id="access-role-code" onChange={(event) => setCode(event.target.value)} required value={code} />
          </label>
        ) : null}
        <label className="access-form-field" htmlFor="access-role-name">
          <span className="field-label">{t('common.name')}</span>
          <input className="field-control" disabled={disabled || selected?.protected} id="access-role-name" onChange={(event) => setName(event.target.value)} required value={name} />
        </label>
        <label className="access-form-field" htmlFor="access-role-description">
          <span className="field-label">{t('common.description')}</span>
          <input className="field-control" disabled={disabled || selected?.protected} id="access-role-description" onChange={(event) => setDescription(event.target.value)} value={description} />
        </label>
        <div className="access-form-actions">
          <button className="button" disabled={disabled || Boolean(selected?.protected) || !name.trim() || (!selected && !code.trim())} type="submit">{selected ? t('common.actions.save') : t('access.createRole')}</button>
          {selected ? <button className="button secondary" disabled={disabled} onClick={() => { setSelectedId(''); setCode(''); setName(''); setDescription(''); }} type="button">{t('common.actions.cancel')}</button> : null}
        </div>
      </form>
      <div className="table-scroll">
        <table>
          <thead><tr><th>{t('copy.role_c3f104d1')}</th><th>{t('common.code')}</th><th>{t('copy.permissions_d06d5557')}</th><th>{t('copy.assignments_057d58c7')}</th><th>{t('common.status')}</th><th>{t('common.actionColumn')}</th></tr></thead>
          <tbody>
            {runtime.roles.length === 0 ? <tr><td className="table-empty" colSpan={6}>{t('access.noRoles')}</td></tr> : null}
            {runtime.roles.map((role) => (
              <tr key={role.id}>
                <td>{role.name}{role.protected ? <small className="table-secondary">{t('access.protectedRole')}</small> : null}</td>
                <td>{role.code}</td><td>{role.permission_ids.length}</td><td>{runtime.assignments.filter((assignment) => assignment.role_id === role.id && assignment.status === 'active').length}</td><td>{accessLabel(role.status, t)}</td>
                <td>
                  <div className="access-table-actions">
                    <button className="button secondary" disabled={disabled || role.protected} onClick={() => selectRole(role)} title={role.protected ? t('access.protectedRoleHelp') : undefined} type="button">{t('common.actions.configure')}</button>
                    <button className="button secondary" disabled={disabled} onClick={() => {
                      const suffix = Date.now().toString().slice(-6);
                      void mutate(() => duplicateOrganizationRole(role.id, { code: `${role.code}.copy-${suffix}`, name: t('access.roleCopyName', { name: role.name }) }), t('access.roleDuplicated'));
                    }} type="button">{t('access.duplicate')}</button>
                    {role.status === 'inactive' ? <button className="button secondary" disabled={disabled || role.protected} onClick={() => void mutate(() => setOrganizationRoleStatus(role.id, 'active'), t('access.roleActivated'))} title={role.protected ? t('access.protectedRoleHelp') : undefined} type="button">{t('access.activate')}</button> : role.status === 'active' ? <button className="button danger administrative-destructive-action" disabled={disabled || role.protected} onClick={() => requestConfirmation({ title: t('confirmation.deactivateRoleTitle', { name: role.name }), description: t('confirmation.deactivateRoleEffect'), confirmLabel: t('access.deactivate'), action: () => mutate(() => setOrganizationRoleStatus(role.id, 'inactive'), t('access.roleDeactivated')) })} title={role.protected ? t('access.protectedRoleHelp') : undefined} type="button">{t('access.deactivate')}</button> : null}
                    <button className="button danger administrative-destructive-action" disabled={disabled || role.protected || role.status === 'archived'} onClick={() => requestConfirmation({ title: t('confirmation.archiveRoleTitle', { name: role.name }), description: t('confirmation.archiveRoleEffect'), confirmLabel: t('access.archive'), action: () => mutate(() => archiveOrganizationRole(role.id), t('access.roleArchived')) })} title={role.protected ? t('access.protectedRoleHelp') : undefined} type="button">{t('access.archive')}</button>
                    <button className="button danger administrative-destructive-action" disabled={disabled || role.protected} onClick={() => requestConfirmation({ title: t('confirmation.deleteRoleTitle', { name: role.name }), description: t('confirmation.deleteRoleEffect'), confirmLabel: t('access.delete'), action: () => mutate(() => deleteOrganizationRole(role.id), t('access.roleDeleted')) })} title={role.protected ? t('access.protectedRoleHelp') : undefined} type="button">{t('access.delete')}</button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function PermissionsView({ runtime, disabled, mutate }: ViewProps) {
  const { t } = useI18n();
  const editableRoles = runtime.roles.filter((role) => !role.protected && role.status === 'active');
  const [roleId, setRoleId] = useState('');
  const [filter, setFilter] = useState('');
  const role = runtime.roles.find((candidate) => candidate.id === roleId);
  const permissions = useMemo(() => {
    const query = filter.trim().toLowerCase();
    return runtime.permissions.filter((permission) => !query || permission.key.toLowerCase().includes(query));
  }, [filter, runtime.permissions]);
  const permissionGroups = useMemo(
    () => [...new Set(permissions.map((permission) => permission.resource))],
    [permissions],
  );

  return (
    <section className="table-card">
      <h2>{t('copy.permissions_d06d5557')}</h2>
      <div className="access-form-grid">
        <label className="access-form-field" htmlFor="access-permission-role">
          <span className="field-label">{t('copy.role_c3f104d1')}</span>
          <select className="field-control" id="access-permission-role" onChange={(event) => setRoleId(event.target.value)} value={roleId}>
            <option value="">{t('access.selectRole')}</option>
            {editableRoles.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </label>
        <label className="access-form-field" htmlFor="access-permission-filter">
          <span className="field-label">{t('common.actions.search')}</span>
          <input className="field-control" id="access-permission-filter" onChange={(event) => setFilter(event.target.value)} value={filter} />
        </label>
      </div>
      <div className="table-scroll">
        <table>
          <thead><tr><th>{t('copy.resource_021493f3')}</th><th>{t('copy.action_97c89a4d')}</th><th>{t('common.description')}</th><th>{t('copy.assigned_e24e824b')}</th></tr></thead>
          {permissionGroups.length === 0 ? <tbody><tr><td className="table-empty" colSpan={4}>{t('access.noPermissions')}</td></tr></tbody> : null}
          {permissionGroups.map((resource) => <tbody key={resource}>
            <tr className="permission-group-row"><th colSpan={4} scope="rowgroup">{accessResourceLabel(resource, t)} <small className="table-secondary"><code>{resource}</code></small></th></tr>
            {permissions.filter((permission) => permission.resource === resource).map((permission) => {
              const assigned = role?.permission_ids.includes(permission.id) ?? false;
              return <tr key={permission.id}><td>{accessResourceLabel(permission.resource, t)}<small className="table-secondary"><code>{permission.resource}</code></small></td><td>{accessLabel(permission.action, t)}<small className="table-secondary"><code>{permission.action}</code></small></td><td>{permissionDescription(permission.resource, permission.action, t)}<small className="table-secondary"><code>{permission.key}</code></small></td><td><input aria-label={`${role?.name || t('access.noRoleSelected')}: ${permission.key}`} checked={assigned} disabled={disabled || !role || !permission.delegable} onChange={(event) => void mutate(() => setOrganizationRolePermission(roleId, permission.id, event.target.checked), t('access.permissionUpdated'))} title={!permission.delegable ? t('access.permissionNotDelegable') : undefined} type="checkbox" /></td></tr>;
            })}
          </tbody>)}
        </table>
      </div>
      <details className="advanced-panel">
        <summary>{t('access.permissionNotDelegable')}</summary>
        <div className="advanced-panel-content">
          <p>{t('access.readOnly')}</p>
          <table>
            <thead><tr><th>{t('copy.resource_021493f3')}</th><th>{t('copy.action_97c89a4d')}</th><th>{t('common.description')}</th></tr></thead>
            <tbody>
              {runtime.non_delegable_permissions.map((permission) => <tr key={permission.id}><td>{accessResourceLabel(permission.resource, t)}<small className="table-secondary"><code>{permission.resource}</code></small></td><td>{accessLabel(permission.action, t)}<small className="table-secondary"><code>{permission.action}</code></small></td><td>{permissionDescription(permission.resource, permission.action, t)}<small className="table-secondary"><code>{permission.key}</code></small></td></tr>)}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}

function AssignmentsView({ runtime, disabled, mutate, requestConfirmation }: ViewProps) {
  const { t } = useI18n();
  const activeUsers = runtime.users.filter((user) => user.membership_status === 'active');
  const activeRoles = runtime.roles.filter((role) => role.status === 'active');
  const [membershipId, setMembershipId] = useState('');
  const [roleId, setRoleId] = useState('');
  const selectedRole = activeRoles.find((role) => role.id === roleId);
  const selectedRoleHasGuidance = roleSelectionHasGuidance(runtime, selectedRole);

  async function submitAssignment(event: FormEvent) {
    event.preventDefault();
    if (!membershipId || !selectedRole) return;
    const saved = await mutate(
      () => createOrganizationAssignment(membershipId, selectedRole.id),
      t('access.assignmentCreated'),
    );
    if (saved) {
      setMembershipId('');
      setRoleId('');
    }
  }

  return (
    <section className="table-card">
      <h2>{t('copy.assignments_057d58c7')}</h2>
      <form className="access-form-grid" onSubmit={(event) => void submitAssignment(event)}>
        <label className="access-form-field" htmlFor="access-assignment-user">
          <span className="field-label">{t('access.user')}</span>
          <select className="field-control" disabled={disabled || activeUsers.length === 0} id="access-assignment-user" onChange={(event) => setMembershipId(event.target.value)} required value={membershipId}>
            <option value="">{t('access.selectIdentity')}</option>
            {activeUsers.map((user) => <option key={user.membership_id} value={user.membership_id}>{user.display_name || user.email}</option>)}
          </select>
        </label>
        <label className="access-form-field" htmlFor="access-assignment-role">
          <span className="field-label">{t('copy.role_c3f104d1')}</span>
          <select
            aria-describedby={selectedRoleHasGuidance ? 'access-assignment-role-guidance' : undefined}
            className="field-control"
            disabled={disabled || activeRoles.length === 0}
            id="access-assignment-role"
            onChange={(event) => setRoleId(event.target.value)}
            required
            value={roleId}
          >
            <option value="">{t('access.selectRole')}</option>
            {activeRoles.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}
          </select>
        </label>
        <RoleSelectionGuidance id="access-assignment-role-guidance" role={selectedRole} runtime={runtime} />
        <div className="access-form-actions">
          <button className="button" disabled={disabled || !membershipId || !selectedRole} type="submit">{t('access.assignRole')}</button>
          <button className="button secondary" disabled={disabled || (!membershipId && !roleId)} onClick={() => { setMembershipId(''); setRoleId(''); }} type="button">{t('common.actions.cancel')}</button>
        </div>
      </form>
      <div className="table-scroll">
        <table>
          <thead><tr><th>{t('access.user')}</th><th>{t('access.email')}</th><th>{t('common.type')}</th><th>{t('copy.role_c3f104d1')}</th><th>{t('common.status')}</th><th>{t('common.actionColumn')}</th></tr></thead>
          <tbody>{runtime.assignments.length === 0 ? <tr><td className="table-empty" colSpan={6}>{t('access.noAssignments')}</td></tr> : null}{runtime.assignments.map((assignment) => <tr key={assignment.id}><td>{assignment.display_name || assignment.email}</td><td>{assignment.email}<small className="table-secondary">{accessLabel(assignment.identity_status, t)}</small></td><td>{accessLabel(assignment.identity_type, t)}</td><td>{roleLabel(runtime, assignment.role_id, t('access.unknownRole'))}</td><td>{accessLabel(assignment.membership_status, t)} · {accessLabel(assignment.status, t)}</td><td>{assignment.status === 'active' ? <div className="access-table-actions"><button className="button danger administrative-destructive-action" disabled={disabled} onClick={() => requestConfirmation({ title: t('confirmation.removeAssignmentTitle', { user: assignment.display_name || assignment.email, role: roleLabel(runtime, assignment.role_id, t('access.unknownRole')) }), description: t('confirmation.removeAssignmentEffect'), confirmLabel: t('common.actions.remove'), action: () => mutate(() => removeOrganizationAssignment(assignment.id), t('access.assignmentRemoved')) })} type="button">{t('common.actions.remove')}</button></div> : null}</td></tr>)}</tbody>
        </table>
      </div>
      {runtime.technical_principals.length > 0 ? <details className="advanced-panel">
        <summary><LocalizedText id="copy.technical_identities_and_validation_records_e5521cba" /></summary>
        <div className="advanced-panel-content">
          <table>
            <thead><tr><th>{t('common.type')}</th><th>{t('access.user')}</th><th>{t('copy.role_c3f104d1')}</th><th>{t('common.status')}</th></tr></thead>
            <tbody>{runtime.technical_principals.map((principal) => <tr key={principal.assignment_id}><td>{localizedProductLabel(principal.principal_type, t)}</td><td><code>{principal.principal_id}</code></td><td>{principal.role_name}</td><td>{localizedProductLabel(principal.status, t)}</td></tr>)}</tbody>
          </table>
        </div>
      </details> : null}
    </section>
  );
}

function PoliciesView({ runtime, disabled, mutate, requestConfirmation }: ViewProps) {
  const { t } = useI18n();
  const [selectedId, setSelectedId] = useState('');
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [effect, setEffect] = useState<'allow' | 'deny'>('deny');
  const [rules, setRules] = useState('{\n  "principals": { "ids": [] },\n  "permissions": []\n}');
  const [jsonError, setJsonError] = useState<string | null>(null);
  const activeUsers = runtime.users.filter((user) => user.membership_status === 'active');
  const delegablePermissions = runtime.permissions.filter((permission) => permission.delegable);
  const [targetUserId, setTargetUserId] = useState('');
  const [targetPermission, setTargetPermission] = useState('');

  function resetPolicyForm() {
    setSelectedId('');
    setCode('');
    setName('');
    setEffect('deny');
    setRules('{\n  "principals": { "ids": [] },\n  "permissions": []\n}');
    setTargetUserId('');
    setTargetPermission('');
    setJsonError(null);
  }

  function selectPolicy(policy: OrganizationAccessPolicy) {
    setSelectedId(policy.id);
    setName(policy.name);
    setEffect(policy.effect);
    setRules(JSON.stringify(policy.rules, null, 2));
    setTargetUserId('');
    setTargetPermission('');
    setJsonError(null);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(rules) as Record<string, unknown>;
      setJsonError(null);
    } catch {
      setJsonError(t('access.invalidPolicyJson'));
      return;
    }
    const saved = selectedId
      ? await mutate(() => updateOrganizationPolicy(selectedId, { name, effect, rules: parsed }), t('access.policyUpdated'))
      : await mutate(() => createOrganizationPolicy({ code, name, effect, rules: parsed }), t('access.policyCreated'));
    if (saved) resetPolicyForm();
  }

  function addReadableTarget() {
    try {
      const parsed = JSON.parse(rules) as {
        principals?: { ids?: unknown[] };
        permissions?: unknown[];
      };
      const principalIds = Array.isArray(parsed.principals?.ids)
        ? parsed.principals.ids.map(String)
        : [];
      const permissions = Array.isArray(parsed.permissions)
        ? parsed.permissions.map(String)
        : [];
      if (targetUserId && !principalIds.includes(targetUserId)) principalIds.push(targetUserId);
      if (targetPermission && !permissions.includes(targetPermission)) permissions.push(targetPermission);
      setRules(JSON.stringify({
        ...parsed,
        principals: { ...(parsed.principals || {}), ids: principalIds },
        permissions,
      }, null, 2));
      setTargetUserId('');
      setTargetPermission('');
      setJsonError(null);
    } catch {
      setJsonError(t('access.invalidPolicyJson'));
    }
  }

  return (
    <section className="table-card">
      <h2>{t('copy.policies_8d611849')}</h2>
      <form className="policy-form" onSubmit={(event) => void submit(event)}>
        {!selectedId ? (
          <label className="access-form-field" htmlFor="access-policy-code">
            <span className="field-label">{t('common.code')}</span>
            <input className="field-control" disabled={disabled} id="access-policy-code" onChange={(event) => setCode(event.target.value)} required value={code} />
          </label>
        ) : null}
        <label className="access-form-field" htmlFor="access-policy-name">
          <span className="field-label">{t('common.name')}</span>
          <input className="field-control" disabled={disabled} id="access-policy-name" onChange={(event) => setName(event.target.value)} required value={name} />
        </label>
        <label className="access-form-field" htmlFor="access-policy-effect">
          <span className="field-label">{t('copy.effect_720b5dbc')}</span>
          <select className="field-control" disabled={disabled} id="access-policy-effect" onChange={(event) => setEffect(event.target.value as 'allow' | 'deny')} value={effect}><option value="deny">{t('access.deny')}</option><option value="allow">{t('access.allow')}</option></select>
        </label>
        <label className="access-form-field" htmlFor="access-policy-user">
          <span className="field-label">{t('access.user')}</span>
          <select className="field-control" disabled={disabled || activeUsers.length === 0} id="access-policy-user" onChange={(event) => setTargetUserId(event.target.value)} value={targetUserId}>
            <option value="">{t('access.selectIdentity')}</option>
            {activeUsers.map((user) => <option key={user.user_id} value={user.user_id}>{user.display_name || user.email}</option>)}
          </select>
        </label>
        <label className="access-form-field" htmlFor="access-policy-permission">
          <span className="field-label">{t('copy.permissions_d06d5557')}</span>
          <select className="field-control" disabled={disabled || delegablePermissions.length === 0} id="access-policy-permission" onChange={(event) => setTargetPermission(event.target.value)} value={targetPermission}>
            <option value="">{t('access.selectPermission')}</option>
            {delegablePermissions.map((permission) => <option key={permission.id} value={permission.key}>{permission.key}</option>)}
          </select>
        </label>
        <button className="button secondary" disabled={disabled || !targetUserId || !targetPermission} onClick={addReadableTarget} type="button">{t('access.addPolicyTarget')}</button>
        <label className="access-form-field policy-rules-field" htmlFor="access-policy-rules"><span className="field-label">{t('access.policyRules')}</span><textarea className="field-control code-input" disabled={disabled} id="access-policy-rules" onChange={(event) => setRules(event.target.value)} rows={8} value={rules} /></label>
        {jsonError ? <p className="form-error" role="alert">{jsonError}</p> : null}
        <div className="access-form-actions"><button className="button" disabled={disabled || !name.trim() || (!selectedId && !code.trim())} type="submit">{selectedId ? t('common.actions.save') : t('access.createPolicy')}</button>{selectedId ? <button className="button secondary" disabled={disabled} onClick={resetPolicyForm} type="button">{t('common.actions.cancel')}</button> : null}</div>
      </form>
      <div className="table-scroll">
        <table>
          <thead><tr><th>{t('copy.policy_bb9cf141')}</th><th>{t('copy.effect_720b5dbc')}</th><th>{t('common.status')}</th><th>{t('common.actionColumn')}</th></tr></thead>
          <tbody>{runtime.policies.length === 0 ? <tr><td className="table-empty" colSpan={4}>{t('access.noPolicies')}</td></tr> : null}{runtime.policies.map((policy) => <tr key={policy.id}><td>{policy.name}<small className="table-secondary">{policy.code}</small></td><td>{accessLabel(policy.effect, t)}</td><td>{accessLabel(policy.status, t)}</td><td><div className="access-table-actions"><button className="button secondary" disabled={disabled} onClick={() => selectPolicy(policy)} type="button">{t('common.actions.configure')}</button>{policy.status !== 'active' ? <button className="button secondary" disabled={disabled} onClick={() => void mutate(() => setOrganizationPolicyStatus(policy.id, 'active'), t('access.policyActivated'))} type="button">{t('access.activate')}</button> : <button className="button danger administrative-destructive-action" disabled={disabled} onClick={() => requestConfirmation({ title: t('confirmation.deactivatePolicyTitle', { name: policy.name }), description: t('confirmation.deactivatePolicyEffect'), confirmLabel: t('access.deactivate'), action: () => mutate(() => setOrganizationPolicyStatus(policy.id, 'inactive'), t('access.policyDeactivated')) })} type="button">{t('access.deactivate')}</button>}<button className="button danger administrative-destructive-action" disabled={disabled || policy.status === 'archived'} onClick={() => requestConfirmation({ title: t('confirmation.archivePolicyTitle', { name: policy.name }), description: t('confirmation.archivePolicyEffect'), confirmLabel: t('access.archive'), action: () => mutate(() => setOrganizationPolicyStatus(policy.id, 'archived'), t('access.policyArchived')) })} type="button">{t('access.archive')}</button></div></td></tr>)}</tbody>
        </table>
      </div>
    </section>
  );
}
