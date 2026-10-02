'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { useI18n } from '../../i18n/I18nProvider';
import { authApi, type ManagedAuthSession, type SessionStatusFilter } from '../../lib/auth-api';
import { localizedApiError } from '../../lib/presentation';
import { sessionDeviceLabel } from '../../lib/session-device';
import { useAuth } from './AuthContext';

const when = (value: string | null) => value ? new Date(value).toLocaleString() : '—';
const PAGE_SIZE = 10;

export function MySessions() {
  const { t } = useI18n();
  const { checkSession } = useAuth();
  const [sessions, setSessions] = useState<ManagedAuthSession[]>([]);
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<SessionStatusFilter>('all');
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const loadSequence = useRef(0);
  const load = useCallback(async () => {
    const sequence = ++loadSequence.current;
    try {
      const page = await authApi.sessions(statusFilter, offset, PAGE_SIZE);
      if (sequence !== loadSequence.current) return;
      setSessions(page.sessions); setTotal(page.total); setError(null);
    }
    catch (cause) { if (sequence === loadSequence.current) setError(localizedApiError(cause, t, 'sessions.loadFailed')); }
  }, [offset, statusFilter, t]);
  useEffect(() => { if (open) void load(); }, [load, open]);
  const revoke = async (session: ManagedAuthSession) => {
    setPending(true);
    try {
      await authApi.revokeSession(session.id);
      setError(null);
      if (session.current) await checkSession(); else await load();
    } catch (cause) { setError(localizedApiError(cause, t, 'sessions.actionFailed')); }
    finally { setPending(false); }
  };
  return <section className="card my-sessions" data-session-management="self">
    <button className="button secondary" onClick={() => setOpen((value) => !value)} type="button">{t('sessions.mySessions')}</button>
    {open ? <><div className="section-header"><h2>{t('sessions.mySessions')}</h2><p>{t('sessions.deviceNotice')}</p></div>{error ? <p className="form-error" role="alert">{error}</p> : null}<div className="basic-filters"><select aria-label={t('sessions.filter')} className="field-control" onChange={(event) => { setStatusFilter(event.target.value as SessionStatusFilter); setOffset(0); }} value={statusFilter}><option value="active">{t('sessions.active')}</option><option value="expired">{t('sessions.expired')}</option><option value="revoked">{t('sessions.revoked')}</option><option value="all">{t('sessions.all')}</option></select><button className="button secondary" disabled={pending} onClick={() => { setPending(true); setError(null); void authApi.revokeOtherSessions().then(load).catch((cause) => setError(localizedApiError(cause, t, 'sessions.actionFailed'))).finally(() => setPending(false)); }} type="button">{t('sessions.revokeOthers')}</button></div><div className="table-scroll"><table><thead><tr><th>{t('sessions.device')}</th><th>{t('sessions.started')}</th><th>{t('sessions.activity')}</th><th>{t('sessions.idleExpiry')}</th><th>{t('sessions.absoluteExpiry')}</th><th>{t('common.status')}</th><th>{t('common.actionColumn')}</th></tr></thead><tbody>{sessions.map((session) => <tr key={session.id}><td>{sessionDeviceLabel(session.user_agent, t('sessions.on'), t('sessions.unknownDevice'))}<small className="table-secondary">{session.client_ip || '—'}{session.current ? ` · ${t('sessions.current')}` : ''}</small>{session.user_agent ? <details><summary>{t('sessions.advancedEvidence')}</summary><code>{session.user_agent}</code></details> : null}</td><td>{when(session.created_at)}</td><td>{when(session.last_activity_at)}</td><td>{when(session.idle_expires_at)}</td><td>{when(session.absolute_expires_at)}</td><td>{session.status}</td><td><button className="button secondary" disabled={pending || session.status !== 'active'} onClick={() => void revoke(session)} type="button">{t('sessions.revoke')}</button></td></tr>)}</tbody></table></div><div className="access-table-actions"><span>{t('sessions.pageSummary').replace('{shown}', String(sessions.length)).replace('{total}', String(total))}</span><button className="button secondary" disabled={pending || offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} type="button">{t('sessions.previous')}</button><button className="button secondary" disabled={pending || offset + sessions.length >= total} onClick={() => setOffset(offset + PAGE_SIZE)} type="button">{t('sessions.next')}</button></div></> : null}
  </section>;
}
