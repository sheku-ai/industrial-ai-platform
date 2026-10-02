'use client';

import { useCallback, useEffect, useState, type FormEvent } from 'react';

import { useI18n } from '../../i18n/I18nProvider';
import { localizedApiError } from '../../lib/presentation';
import { sessionManagementApi, type PolicyUpdate, type SessionPolicy } from '../../lib/session-management-api';

const fields: (keyof Pick<PolicyUpdate, 'idle_timeout_seconds' | 'absolute_timeout_seconds' | 'max_concurrent_sessions' | 'activity_write_interval_seconds' | 'remember_idle_timeout_seconds' | 'remember_absolute_timeout_seconds' | 'retention_days'>)[] = ['idle_timeout_seconds', 'absolute_timeout_seconds', 'max_concurrent_sessions', 'activity_write_interval_seconds', 'remember_idle_timeout_seconds', 'remember_absolute_timeout_seconds', 'retention_days'];
const bounds: Record<(typeof fields)[number], { min: number; max: number }> = {
  idle_timeout_seconds: { min: 60, max: 86_400 },
  absolute_timeout_seconds: { min: 300, max: 2_592_000 },
  max_concurrent_sessions: { min: 1, max: 100 },
  activity_write_interval_seconds: { min: 30, max: 3_600 },
  remember_idle_timeout_seconds: { min: 60, max: 604_800 },
  remember_absolute_timeout_seconds: { min: 300, max: 31_536_000 },
  retention_days: { min: 1, max: 3_650 },
};

export function SessionPolicyManager() {
  const { t } = useI18n();
  const [policy, setPolicy] = useState<SessionPolicy | null>(null);
  const [mode, setMode] = useState<PolicyUpdate['application_mode']>('new_sessions_only');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try { setPolicy(await sessionManagementApi.policy()); setError(null); }
    catch (cause) { setError(localizedApiError(cause, t, 'sessions.loadFailed')); }
  }, [t]);
  useEffect(() => { void load(); }, [load]);
  if (!policy) return <section className="card"><h2>{t('sessions.policy')}</h2>{error ? <p className="form-error" role="alert">{error}</p> : <p>{t('common.loading')}</p>}</section>;
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setPending(true); setError(null);
    const form = new FormData(event.currentTarget);
    const payload = Object.fromEntries(fields.map((field) => [field, Number(form.get(field))])) as unknown as PolicyUpdate;
    payload.remember_me_enabled = form.get('remember_me_enabled') === 'on';
    payload.application_mode = mode;
    if (payload.idle_timeout_seconds > payload.absolute_timeout_seconds || payload.remember_idle_timeout_seconds > payload.remember_absolute_timeout_seconds || payload.activity_write_interval_seconds >= payload.idle_timeout_seconds || payload.activity_write_interval_seconds >= payload.remember_idle_timeout_seconds) {
      setError(t('sessions.policyInvalid')); setPending(false); return;
    }
    try { setPolicy(await sessionManagementApi.updatePolicy(payload)); }
    catch (cause) { setError(localizedApiError(cause, t, 'sessions.policyFailed')); }
    finally { setPending(false); }
  };
  return <section className="table-card" data-session-management="policy"><header className="section-header"><h2>{t('sessions.policy')}</h2><p>{t('sessions.policyHelp')}</p></header>{error ? <p className="form-error" role="alert">{error}</p> : null}<form className="access-form-grid" key={policy.version} onSubmit={(event) => void submit(event)}>{fields.map((field) => <label className="access-form-field" key={field}><span className="field-label">{t(`sessions.${field}`)}</span><input className="field-control" defaultValue={policy[field]} max={bounds[field].max} min={bounds[field].min} name={field} required type="number" /></label>)}<label className="checkbox-row"><input defaultChecked={policy.remember_me_enabled} name="remember_me_enabled" type="checkbox" /><span>{t('sessions.rememberEnabled')}</span></label><label className="access-form-field"><span className="field-label">{t('sessions.applicationMode')}</span><select className="field-control" onChange={(event) => setMode(event.target.value as PolicyUpdate['application_mode'])} value={mode}><option value="new_sessions_only">{t('sessions.newOnly')}</option><option value="restrict_existing">{t('sessions.restrictExisting')}</option></select></label><button className="button primary" disabled={pending} type="submit">{t('common.actions.save')}</button></form></section>;
}
