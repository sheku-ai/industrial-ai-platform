'use client';

import { useEffect, useMemo, useState, type FormEvent } from 'react';

import { useI18n } from '../../i18n/I18nProvider';
import { globalUserApi, type GlobalManagedUser, type GlobalUserRuntime } from '../../lib/global-user-management-api';
import { localizedApiError, localizedProductLabel } from '../../lib/presentation';
import { ActionConfirmationDialog } from '../layout/ActionConfirmationDialog';
import { AdminUserSessions } from './AdminUserSessions';
import { GlobalUserProfileEditor } from './GlobalUserProfileEditor';

type Confirmation = { action: 'activate' | 'deactivate' | 'reset' | 'revoke' | 'delete'; user: GlobalManagedUser };

export function GlobalUserManager({ runtime, refresh }: { runtime: GlobalUserRuntime; refresh: () => Promise<void> }) {
  const { t } = useI18n();
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('all');
  const [selectedUserId, setSelectedUserId] = useState(runtime.users[0]?.user_id ?? '');
  const [creationOpen, setCreationOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [username, setUsername] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [email, setEmail] = useState('');
  const [temporaryPassword, setTemporaryPassword] = useState('');
  const [organizationId, setOrganizationId] = useState('');
  const [organizationRoleId, setOrganizationRoleId] = useState('');
  const [deleteConfirmation, setDeleteConfirmation] = useState('');
  const selected = runtime.users.find((user) => user.user_id === selectedUserId) ?? null;
  const filtered = useMemo(() => runtime.users.filter((user) => {
    const haystack = `${user.username} ${user.display_name ?? ''} ${user.email}`.toLowerCase();
    return haystack.includes(query.trim().toLowerCase()) && (status === 'all' || user.status === status);
  }), [query, runtime.users, status]);
  const organizationRoles = runtime.organization_roles.filter((role) => role.organization_id === organizationId);

  useEffect(() => {
    if (selected || runtime.users.length === 0) return;
    setSelectedUserId(runtime.users[0].user_id);
  }, [runtime.users, selected]);

  const mutate = async <Result,>(operation: () => Promise<Result>): Promise<Result | null> => {
    if (pending) return null;
    setPending(true); setError(null); setNotice(null);
    try {
      const result = await operation();
      setNotice(t('globalUsers.success'));
      setTemporaryPassword('');
      await refresh();
      return result;
    } catch (cause) {
      setError(localizedApiError(cause, t, 'globalUsers.failed'));
      return null;
    } finally { setPending(false); }
  };

  const create = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const result = await mutate(() => globalUserApi.create({ username, display_name: displayName, email, temporary_password: temporaryPassword }));
    if (result?.user) {
      setSelectedUserId(result.user.user_id);
      setCreationOpen(false);
      setUsername(''); setDisplayName(''); setEmail('');
    }
  };

  const saveProfile = async (
    userId: string,
    changes: { username?: string; display_name?: string; email?: string },
  ): Promise<GlobalManagedUser | null> => {
    const result = await mutate(() => globalUserApi.update(userId, changes));
    return result?.user ?? null;
  };

  const confirm = async () => {
    if (!confirmation) return;
    const { action, user } = confirmation;
    await mutate(() => action === 'reset' ? globalUserApi.resetPassword(user.user_id, temporaryPassword) : action === 'revoke' ? globalUserApi.revokeSessions(user.user_id) : action === 'delete' ? globalUserApi.delete(user.user_id) : globalUserApi.setStatus(user.user_id, action === 'activate'));
    setConfirmation(null);
    setDeleteConfirmation('');
  };

  return (
    <section className="table-card global-user-manager" data-global-user-management="ready">
      <header className="section-header"><span className="eyebrow">{t('navigation.platform')}</span><h2>{t('globalUsers.title')}</h2><p>{t('globalUsers.description')}</p></header>
      {notice ? <p className="form-success" role="status">{notice}</p> : null}
      {error ? <p className="form-error" role="alert">{error}</p> : null}
      {creationOpen ? <form className="access-form-grid" data-global-user-creation="open" onSubmit={(event) => void create(event)}>
        <label className="access-form-field"><span className="field-label">{t('globalUsers.username')}</span><input autoComplete="username" className="field-control" disabled={pending} id="global-user-create-username" maxLength={128} name="username" onChange={(event) => setUsername(event.target.value)} required value={username} /></label>
        <label className="access-form-field"><span className="field-label">{t('globalUsers.displayName')}</span><input className="field-control" disabled={pending} maxLength={255} name="name" onChange={(event) => setDisplayName(event.target.value)} required value={displayName} /></label>
        <label className="access-form-field"><span className="field-label">{t('globalUsers.email')}</span><input autoComplete="email" className="field-control" disabled={pending} id="global-user-create-email" maxLength={320} name="email" onChange={(event) => setEmail(event.target.value)} required type="email" value={email} /></label>
        <label className="access-form-field"><span className="field-label">{t('globalUsers.temporaryPassword')}</span><input autoComplete="new-password" className="field-control" disabled={pending} name="new-password" onChange={(event) => setTemporaryPassword(event.target.value)} required type="password" value={temporaryPassword} /></label>
        <div className="access-form-actions"><button className="button secondary" disabled={pending} onClick={() => setCreationOpen(false)} type="button">{t('common.actions.cancel')}</button><button className="button primary" disabled={pending} type="submit">{t('globalUsers.create')}</button></div>
      </form> : <button className="button primary" disabled={pending} onClick={() => setCreationOpen(true)} type="button">{t('globalUsers.create')}</button>}
      <div className="basic-filters">
        <input aria-label={t('globalUsers.search')} className="field-control" onChange={(event) => setQuery(event.target.value)} placeholder={t('globalUsers.search')} value={query} />
        <select aria-label={t('common.status')} className="field-control" onChange={(event) => setStatus(event.target.value)} value={status}><option value="all">{t('globalUsers.allStatuses')}</option><option value="active">{t('globalUsers.active')}</option><option value="suspended">{t('globalUsers.inactive')}</option></select>
      </div>
      <table><thead><tr><th>{t('globalUsers.user')}</th><th>{t('common.status')}</th><th>{t('globalUsers.access')}</th><th>{t('globalUsers.sessions')}</th><th>{t('common.actionColumn')}</th></tr></thead><tbody>{filtered.map((user) => <tr key={user.user_id}><td><strong>{user.display_name ?? user.username}</strong><small className="table-secondary">{user.username} · {user.email}</small></td><td>{localizedProductLabel(user.status, t)}{user.must_change_password ? <small className="table-secondary">{t('globalUsers.changePending')}</small> : null}</td><td>{user.global_roles.map((role) => role.name).join(', ') || t('globalUsers.noGlobalRole')}<small className="table-secondary">{t('globalUsers.membershipCount').replace('{count}', String(user.memberships.length))}</small></td><td>{user.active_sessions}</td><td><button className="button secondary" onClick={() => { setCreationOpen(false); setSelectedUserId(user.user_id); }} type="button">{t('common.actions.configure')}</button></td></tr>)}</tbody></table>
      {selected && !creationOpen ? <div className="context-card global-user-detail">
        <h3>{selected.display_name ?? selected.username}</h3>
        <p>{localizedProductLabel(selected.status, t)}{selected.must_change_password ? ` · ${t('globalUsers.changePending')}` : ''}</p>
        <GlobalUserProfileEditor key={selected.user_id} pending={pending} save={saveProfile} selected={selected} />
        <div className="access-table-actions"><button className="button secondary" disabled={pending || !temporaryPassword} onClick={() => setConfirmation({ action: 'reset', user: selected })} type="button">{t('globalUsers.resetPassword')}</button><button className="button secondary" disabled={pending} onClick={() => setConfirmation({ action: 'revoke', user: selected })} type="button">{t('globalUsers.revokeSessions')}</button><button className="button secondary" disabled={pending} onClick={() => setConfirmation({ action: selected.status === 'active' ? 'deactivate' : 'activate', user: selected })} type="button">{t(selected.status === 'active' ? 'globalUsers.deactivate' : 'globalUsers.activate')}</button></div>
        <label className="access-form-field"><span className="field-label">{t('globalUsers.deleteConfirmation').replace('{username}', selected.username)}</span><input className="field-control" disabled={pending} onChange={(event) => setDeleteConfirmation(event.target.value)} value={deleteConfirmation} /></label><button className="button danger" disabled={pending || deleteConfirmation !== selected.username} onClick={() => setConfirmation({ action: 'delete', user: selected })} type="button">{t('globalUsers.delete')}</button>
        <h4>{t('globalUsers.globalRoles')}</h4><div className="global-permission-options">{runtime.global_roles.map((role) => { const assigned = selected.global_roles.some((item) => item.role_id === role.role_id && item.available); return <label className="checkbox-row" key={role.role_id}><input checked={assigned} disabled={pending} onChange={() => void mutate(() => globalUserApi.setGlobalRole(selected.user_id, role.role_id, !assigned))} type="checkbox" /><span>{role.name}<small>{role.code} · {localizedProductLabel(role.status, t)}</small></span></label>; })}</div>{selected.global_roles.filter((role) => !role.available).map((role) => <p className="form-error" key={role.role_id} role="alert">{t('globalUsers.assignedRoleUnavailable')}{role.name ? `: ${role.name}` : ''}</p>)}
        <h4>{t('globalUsers.organizations')}</h4><div className="access-form-grid"><select className="field-control" onChange={(event) => { setOrganizationId(event.target.value); setOrganizationRoleId(''); }} value={organizationId}><option value="">{t('globalUsers.selectOrganization')}</option>{runtime.organizations.map((organization) => <option key={organization.organization_id} value={organization.organization_id}>{organization.name}</option>)}</select><select className="field-control" disabled={!organizationId} onChange={(event) => setOrganizationRoleId(event.target.value)} value={organizationRoleId}><option value="">{t('globalUsers.selectRole')}</option>{organizationRoles.map((role) => <option key={role.role_id} value={role.role_id}>{role.name}</option>)}</select><button className="button secondary" disabled={pending || !organizationId || !organizationRoleId} onClick={() => void mutate(() => globalUserApi.setMembership(selected.user_id, organizationId, organizationRoleId))} type="button">{t('globalUsers.addMembership')}</button></div>
        <ul className="compact-list">{selected.memberships.map((membership) => <li key={membership.membership_id}><strong>{membership.organization_name}</strong><div className="global-permission-options">{runtime.organization_roles.filter((role) => role.organization_id === membership.organization_id).map((role) => { const assigned = membership.roles.some((item) => item.role_id === role.role_id); return <label className="checkbox-row" key={role.role_id}><input checked={assigned} disabled={pending} onChange={() => void mutate(() => globalUserApi.setOrganizationRole(selected.user_id, membership.organization_id, role.role_id, !assigned))} type="checkbox" /><span>{role.name}</span></label>; })}</div><button className="button secondary" disabled={pending} onClick={() => void mutate(() => globalUserApi.setMembership(selected.user_id, membership.organization_id, null))} type="button">{t('common.actions.remove')}</button></li>)}</ul>
        <AdminUserSessions userId={selected.user_id} />
      </div> : null}
      <ActionConfirmationDialog cancelLabel={t('common.actions.cancel')} confirmLabel={t('common.actions.confirm')} description={confirmation?.action === 'delete' ? t('globalUsers.deleteWarning') : confirmation?.action === 'reset' ? t('globalUsers.resetWarning') : t('globalUsers.confirmHelp')} onCancel={() => setConfirmation(null)} onConfirm={() => void confirm()} open={Boolean(confirmation)} pending={pending} title={t('common.actions.confirm')} />
    </section>
  );
}
