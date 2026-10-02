'use client';

import type { ReactNode } from 'react';
import { usePathname } from 'next/navigation';

import { useI18n } from '../../i18n/I18nProvider';
import { useOrganization } from '../organization/OrganizationContext';

export function OrganizationScope({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { organization, organizations, loading, error, errorStatus, refreshOrganizations } = useOrganization();
  const { t } = useI18n();

  if (
    pathname === '/operations'
    || pathname.startsWith('/operations/')
    || pathname === '/scheduler'
    || pathname.startsWith('/scheduler/')
    || pathname === '/security'
    || pathname.startsWith('/security/')
  ) {
    return <div className="platform-scope">{children}</div>;
  }

  if (loading && !organization) {
    return <section className="card workspace-state"><h1>{t('shell.preparingWorkspace')}</h1><p>{t('shell.loadingAuthorizedOrganizations')}</p></section>;
  }

  if (error && !organization) {
    return <section className="card workspace-state"><h1>{t(errorStatus === 403 ? 'errors.accessRequired' : 'shell.organizationsUnavailable')}</h1><p>{error}</p>{errorStatus === 403 ? null : <button className="button secondary" type="button" onClick={() => void refreshOrganizations()}>{t('common.actions.retry')}</button>}</section>;
  }

  if (!organization) {
    return (
      <section className="card workspace-state">
        <span className="eyebrow">{t('shell.getStarted')}</span>
        <h1>{t(organizations.length > 1 ? 'shell.chooseOrganization' : 'shell.noOrganizationAvailable')}</h1>
        <p>
          {organizations.length > 1
            ? t('shell.chooseOrganizationHelp')
            : t('shell.requestOrganizationHelp')}
        </p>
        <ol className="onboarding-steps">
          <li className={organizations.length > 0 ? 'is-ready' : ''}>{t('shell.stepOrganization')}</li>
          <li>{t('shell.stepDocuments')}</li>
          <li>{t('shell.stepKnowledge')}</li>
        </ol>
      </section>
    );
  }

  return <div className="organization-scope">{loading ? <p className="context-message">{t('shell.refreshingAccess')}</p> : null}{children}</div>;
}
