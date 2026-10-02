'use client';

import { type FormEvent, useCallback, useEffect, useMemo, useState } from 'react';

import { useI18n } from '../../i18n/I18nProvider';
import {
  listGlobalRolePermissions,
  listGlobalRoles,
  reconcileGlobalRole,
  setGlobalRoleStatus,
  type GlobalRole,
  type GlobalRolePermission,
} from '../../lib/global-role-management-api';
import { PlatformApiError } from '../../lib/platform-api';
import { localizedApiError, localizedProductLabel } from '../../lib/presentation';
import { ActionConfirmationDialog } from '../layout/ActionConfirmationDialog';
import { LocalizedText } from '../layout/LocalizedText';

type StatusConfirmation = {
  role: GlobalRole;
  active: boolean;
};

export function GlobalRoleManager() {
  const { t } = useI18n();
  const [roles, setRoles] = useState<GlobalRole[]>([]);
  const [permissions, setPermissions] = useState<GlobalRolePermission[]>([]);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [selectedPermissions, setSelectedPermissions] = useState<Set<string>>(new Set());
  const [confirmation, setConfirmation] = useState<StatusConfirmation | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [roleCatalog, permissionCatalog] = await Promise.all([
        listGlobalRoles(),
        listGlobalRolePermissions(),
      ]);
      setRoles(roleCatalog);
      setPermissions(permissionCatalog);
      setForbidden(false);
    } catch (cause) {
      setForbidden(cause instanceof PlatformApiError && cause.status === 403);
      setError(localizedApiError(cause, t, 'access.operationFailed'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const orderedPermissions = useMemo(
    () => [...permissions].sort((left, right) => left.key.localeCompare(right.key)),
    [permissions],
  );

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending || selectedPermissions.size === 0) return;
    setPending(true);
    setError(null);
    setNotice(null);
    try {
      const result = await reconcileGlobalRole({
        code,
        name,
        description: description || undefined,
        permission_keys: [...selectedPermissions],
      });
      setNotice(localizedProductLabel(result.outcome, t));
      setCode('');
      setName('');
      setDescription('');
      setSelectedPermissions(new Set());
      await refresh();
    } catch (cause) {
      setError(localizedApiError(cause, t, 'access.operationFailed'));
    } finally {
      setPending(false);
    }
  };

  const changeStatus = async () => {
    if (!confirmation || pending) return;
    setPending(true);
    setError(null);
    setNotice(null);
    try {
      const result = await setGlobalRoleStatus(confirmation.role.code, confirmation.active);
      setNotice(localizedProductLabel(result.outcome, t));
      setConfirmation(null);
      await refresh();
    } catch (cause) {
      setError(localizedApiError(cause, t, 'access.operationFailed'));
    } finally {
      setPending(false);
    }
  };

  const togglePermission = (permissionKey: string) => {
    setSelectedPermissions((current) => {
      const next = new Set(current);
      if (next.has(permissionKey)) next.delete(permissionKey);
      else next.add(permissionKey);
      return next;
    });
  };

  if (loading && roles.length === 0 && permissions.length === 0) {
    return <section className="card" role="status"><h2><LocalizedText id="copy.roles_47dcc27d" /></h2><p>{t('common.loading')}</p></section>;
  }

  if (forbidden) {
    return <section className="card"><h2>{t('errors.accessRequired')}</h2><p>{error}</p></section>;
  }

  return (
    <section className="table-card" data-global-role-management="ready">
      <header className="section-header">
        <span className="eyebrow">{t('navigation.platform')}</span>
        <h2><LocalizedText id="copy.roles_47dcc27d" /></h2>
        <p>{t('pages.security.description')}</p>
      </header>
      {notice ? <p className="form-success" role="status">{notice}</p> : null}
      {error ? <p className="form-error" role="alert">{error}</p> : null}

      <form className="access-form-grid" onSubmit={(event) => void submit(event)}>
        <label className="access-form-field"><span className="field-label">{t('common.code')}</span><input className="field-control" disabled={pending} maxLength={128} onChange={(event) => setCode(event.target.value)} required value={code} /></label>
        <label className="access-form-field"><span className="field-label">{t('common.name')}</span><input className="field-control" disabled={pending} maxLength={255} onChange={(event) => setName(event.target.value)} required value={name} /></label>
        <label className="access-form-field"><span className="field-label">{t('common.description')}</span><textarea className="field-control" disabled={pending} onChange={(event) => setDescription(event.target.value)} value={description} /></label>
        <fieldset className="global-permission-selector" disabled={pending}>
          <legend><LocalizedText id="copy.permissions_d06d5557" /></legend>
          <div className="global-permission-options">
            {orderedPermissions.map((permission) => (
              <label className="checkbox-row" key={permission.id}>
                <input
                  checked={selectedPermissions.has(permission.key)}
                  onChange={() => togglePermission(permission.key)}
                  type="checkbox"
                />
                <span><code>{permission.key}</code>{permission.description ? <small>{permission.description}</small> : null}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <div className="access-form-actions"><button className="button primary" disabled={pending || selectedPermissions.size === 0} type="submit">{t('common.actions.save')}</button></div>
      </form>

      <table>
        <thead><tr><th>{t('common.name')}</th><th>{t('common.code')}</th><th>{t('common.type')}</th><th>{t('common.status')}</th><th><LocalizedText id="copy.effective_permissions_17c0fe8a" /></th><th>{t('common.actionColumn')}</th></tr></thead>
        <tbody>
          {roles.map((role) => (
            <tr key={role.role_id}>
              <td>{role.name}{role.description ? <small className="table-secondary">{role.description}</small> : null}</td>
              <td><code>{role.code}</code></td>
              <td>{localizedProductLabel(role.scope, t)}</td>
              <td>{localizedProductLabel(role.status, t)}</td>
              <td><ul className="compact-list">{role.permission_keys.map((permissionKey) => <li key={permissionKey}><code>{permissionKey}</code></li>)}</ul></td>
              <td>
                <div className="access-table-actions">
                  <button className="button secondary" disabled={pending || !role.configurable} onClick={() => {
                    setCode(role.code);
                    setName(role.name);
                    setDescription(role.description ?? '');
                    setSelectedPermissions(new Set(role.permission_keys));
                  }} type="button">{t('common.actions.configure')}</button>
                  <button
                    className={role.status === 'active' ? 'button danger administrative-destructive-action' : 'button secondary'}
                    disabled={pending || !role.configurable}
                    onClick={() => setConfirmation({ role, active: role.status !== 'active' })}
                    type="button"
                  >
                    {t(role.status === 'active' ? 'access.deactivate' : 'access.activate')}
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {roles.length === 0 ? <p>{t('common.noItems')}</p> : null}

      <ActionConfirmationDialog
        cancelLabel={t('common.actions.cancel')}
        confirmLabel={t(confirmation?.active ? 'access.activate' : 'access.deactivate')}
        description={confirmation?.role.name ?? ''}
        onCancel={() => { if (!pending) setConfirmation(null); }}
        onConfirm={() => void changeStatus()}
        open={Boolean(confirmation)}
        pending={pending}
        title={t('common.actions.confirm')}
      />
    </section>
  );
}
