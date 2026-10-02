'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { useI18n } from '../../i18n/I18nProvider';
import type { ManagedAuthSession, SessionStatusFilter } from '../../lib/auth-api';
import { localizedApiError } from '../../lib/presentation';
import { sessionDeviceLabel } from '../../lib/session-device';
import { sessionManagementApi } from '../../lib/session-management-api';

export function AdminUserSessions({ userId }: { userId: string }) {
  const { t } = useI18n();
  const [sessions, setSessions] = useState<ManagedAuthSession[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<SessionStatusFilter>('all');
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const activeUserId = useRef(userId);
  const loadSequence = useRef(0);
  activeUserId.current = userId;
  const load = useCallback(async () => {
    const requestedUserId = userId;
    const sequence = ++loadSequence.current;
    try {
      const page = await sessionManagementApi.userSessions(userId, statusFilter, offset, 10);
      if (activeUserId.current !== requestedUserId || sequence !== loadSequence.current) return;
      setSessions(page.sessions); setTotal(page.total); setError(null);
    }
    catch (cause) {
      if (activeUserId.current === requestedUserId && sequence === loadSequence.current) {
        setError(localizedApiError(cause, t, 'sessions.loadFailed'));
      }
    }
  }, [offset, statusFilter, t, userId]);
  useEffect(() => { setSessions([]); setTotal(0); setStatusFilter('all'); setOffset(0); }, [userId]);
  useEffect(() => { void load(); }, [load]);
  const act = async (operation: () => Promise<unknown>) => { setPending(true); setError(null); try { await operation(); await load(); } catch (cause) { setError(localizedApiError(cause, t, 'sessions.actionFailed')); } finally { setPending(false); } };
  return <section className="context-card" data-session-management="administrative"><h4>{t('sessions.userSessions')}</h4>{error ? <p className="form-error" role="alert">{error}</p> : null}<div className="basic-filters"><select aria-label={t('sessions.filter')} className="field-control" onChange={(event) => { setStatusFilter(event.target.value as SessionStatusFilter); setOffset(0); }} value={statusFilter}><option value="active">{t('sessions.active')}</option><option value="expired">{t('sessions.expired')}</option><option value="revoked">{t('sessions.revoked')}</option><option value="all">{t('sessions.all')}</option></select><button className="button secondary" disabled={pending} onClick={() => void act(() => sessionManagementApi.revokeAll(userId))} type="button">{t('sessions.revokeAll')}</button></div><div className="table-scroll"><table><thead><tr><th>{t('sessions.device')}</th><th>{t('sessions.activity')}</th><th>{t('sessions.absoluteExpiry')}</th><th>{t('common.status')}</th><th>{t('sessions.reason')}</th><th>{t('common.actionColumn')}</th></tr></thead><tbody>{sessions.map((session) => <tr key={session.id}><td>{sessionDeviceLabel(session.user_agent, t('sessions.on'), t('sessions.unknownDevice'))}<small className="table-secondary">{session.client_ip || '—'}</small>{session.user_agent ? <details><summary>{t('sessions.advancedEvidence')}</summary><code>{session.user_agent}</code></details> : null}</td><td>{new Date(session.last_activity_at).toLocaleString()}</td><td>{new Date(session.absolute_expires_at).toLocaleString()}</td><td>{session.status}</td><td>{session.revocation_reason || '—'}</td><td><button className="button secondary" disabled={pending || session.status !== 'active'} onClick={() => void act(() => sessionManagementApi.revoke(userId, session.id))} type="button">{t('sessions.revoke')}</button></td></tr>)}</tbody></table></div><div className="access-table-actions"><span>{t('sessions.pageSummary').replace('{shown}', String(sessions.length)).replace('{total}', String(total))}</span><button className="button secondary" disabled={pending || offset === 0} onClick={() => setOffset(Math.max(0, offset - 10))} type="button">{t('sessions.previous')}</button><button className="button secondary" disabled={pending || offset + sessions.length >= total} onClick={() => setOffset(offset + 10)} type="button">{t('sessions.next')}</button></div></section>;
}
