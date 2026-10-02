'use client';

import { useEffect, type ReactNode } from 'react';
import { usePathname, useRouter } from 'next/navigation';

import { useI18n } from '../../i18n/I18nProvider';
import { useAuth } from './AuthContext';
import { ForcedPasswordChange } from './ForcedPasswordChange';

type AuthBoundaryProps = {
  children: ReactNode;
  workspace: ReactNode;
};

export function safeReturnTo(value: string | null | undefined): string | null {
  if (!value?.startsWith('/') || value.startsWith('//')) return null;
  try {
    const target = new URL(value, window.location.origin);
    if (target.origin !== window.location.origin) return null;
    if (target.pathname === '/login' || target.pathname.startsWith('/login/')) return null;
    return `${target.pathname}${target.search}${target.hash}`;
  } catch {
    return null;
  }
}

export function AuthBoundary({ children, workspace }: AuthBoundaryProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { t } = useI18n();
  const { status, principal, checkSession } = useAuth();
  const isLogin = pathname === '/login';

  useEffect(() => {
    if (status === 'authenticated' && isLogin) {
      const returnTo = safeReturnTo(new URLSearchParams(window.location.search).get('returnTo'));
      router.replace(returnTo ?? '/');
      return;
    }
    if (status === 'unauthenticated' && !isLogin) {
      const current = safeReturnTo(
        `${window.location.pathname}${window.location.search}${window.location.hash}`,
      ) ?? '/';
      router.replace(`/login?returnTo=${encodeURIComponent(current)}`);
    }
  }, [isLogin, router, status]);

  if (status === 'checking' || (status === 'authenticated' && isLogin) || (status === 'unauthenticated' && !isLogin)) {
    return (
      <main className="auth-state" id="main-content">
        <section aria-live="polite" className="card auth-state-card" role="status">
          <span className="auth-state-indicator" aria-hidden="true" />
          <h1>{t('auth.checkingTitle')}</h1>
          <p>{t('auth.checkingDescription')}</p>
        </section>
      </main>
    );
  }

  if (status === 'unavailable') {
    return (
      <main className="auth-state" id="main-content">
        <section className="card auth-state-card identity-unavailable" role="alert">
          <h1>{t('auth.unavailableTitle')}</h1>
          <p>{t('auth.unavailableDescription')}</p>
          <button className="button secondary" type="button" onClick={() => void checkSession()}>
            {t('common.actions.retry')}
          </button>
        </section>
      </main>
    );
  }

  if (status === 'authenticated' && principal?.user.must_change_password && !isLogin) {
    return <ForcedPasswordChange />;
  }

  return isLogin ? children : workspace;
}
