'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { useI18n } from '../../i18n/I18nProvider';
import { globalUserApi, type GlobalUserRuntime } from '../../lib/global-user-management-api';
import { PlatformApiError } from '../../lib/platform-api';
import { localizedApiError } from '../../lib/presentation';
import { GlobalRoleManager } from './GlobalRoleManager';
import { GlobalUserManager } from './GlobalUserManager';
import { SessionPolicyManager } from './SessionPolicyManager';

export function GlobalSecurityAdministration() {
  const { t } = useI18n();
  const [runtime, setRuntime] = useState<GlobalUserRuntime | null>(null);
  const [loading, setLoading] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const refreshSequence = useRef(0);
  const refresh = useCallback(async () => {
    const sequence = ++refreshSequence.current;
    setLoading(true); setError(null);
    try {
      const result = await globalUserApi.runtime();
      if (sequence !== refreshSequence.current) return;
      setRuntime(result); setForbidden(false);
    } catch (cause) {
      if (sequence !== refreshSequence.current) return;
      setRuntime(null); setForbidden(cause instanceof PlatformApiError && cause.status === 403); setError(localizedApiError(cause, t, 'globalUsers.failed'));
    } finally { if (sequence === refreshSequence.current) setLoading(false); }
  }, [t]);
  useEffect(() => { void refresh(); }, [refresh]);
  if (loading) return <section className="card" role="status"><h2>{t('globalUsers.title')}</h2><p>{t('common.loading')}</p></section>;
  if (forbidden) return <section className="card" data-global-security-access="required"><h2>{t('errors.accessRequired')}</h2><p>{t('globalUsers.accessRequired')}</p></section>;
  if (!runtime) return <section className="card" role="alert"><h2>{t('globalUsers.unavailable')}</h2><p>{error}</p><button className="button secondary" onClick={() => void refresh()} type="button">{t('common.actions.retry')}</button></section>;
  return <><SessionPolicyManager /><GlobalUserManager refresh={refresh} runtime={runtime} /><GlobalRoleManager /></>;
}
