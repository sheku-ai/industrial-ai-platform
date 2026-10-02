'use client';

import { usePathname, useRouter } from 'next/navigation';
import { useCallback, useEffect, useState, type ReactNode } from 'react';

import { useI18n } from '../../i18n/I18nProvider';
import { installationSetupApi, type InstallationStatus } from '../../lib/installation-setup-api';

type InstallationBoundaryProps = {
  application: ReactNode;
  children: ReactNode;
};

export function InstallationBoundary({ application, children }: InstallationBoundaryProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { t } = useI18n();
  const [status, setStatus] = useState<InstallationStatus | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const isSetup = pathname === '/setup' || pathname.startsWith('/setup/');

  const load = useCallback(async () => {
    setUnavailable(false);
    try {
      setStatus(await installationSetupApi.status());
    } catch {
      setUnavailable(true);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!status) return;
    if (status.state !== 'COMPLETED' && !isSetup) router.replace('/setup');
    if (status.state === 'COMPLETED' && isSetup) router.replace('/login');
  }, [isSetup, router, status]);

  if (unavailable) {
    return (
      <main className="installation-state">
        <section className="card installation-state-card" role="alert">
          <h1>{t('setup.unavailableTitle')}</h1>
          <p>{t('setup.unavailableDescription')}</p>
          <button className="button secondary" onClick={() => void load()} type="button">
            {t('common.actions.retry')}
          </button>
        </section>
      </main>
    );
  }
  if (!status || (status.state !== 'COMPLETED' && !isSetup) || (status.state === 'COMPLETED' && isSetup)) {
    return (
      <main className="installation-state">
        <section aria-live="polite" className="card installation-state-card" role="status">
          <span className="auth-state-indicator" aria-hidden="true" />
          <h1>{t('setup.checkingTitle')}</h1>
          <p>{t('setup.checkingDescription')}</p>
        </section>
      </main>
    );
  }
  return isSetup ? children : application;
}
