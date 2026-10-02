'use client';

import { useOrganization } from './OrganizationContext';
import { useI18n } from '../../i18n/I18nProvider';
import { LanguageSelector } from '../layout/LanguageSelector';
import { localizedStatusLabel } from '../../lib/presentation';

export function OrganizationSelector() {
  const { t } = useI18n();
  const {
    organizations,
    organization,
    loading,
    slowLoading,
    error,
    selectOrganization,
    refreshOrganizations,
  } = useOrganization();
  return (
    <section className={`organization-context${organizations.length === 1 ? ' is-single' : ''}`} aria-label={t('shell.organizationContext')}>
      <div className="organization-context-heading">
        <span>{t('shell.activeOrganization')}</span>
        <strong>{organization?.name ?? (loading ? t('shell.loadingOrganizations') : t('common.notSelected'))}</strong>
      </div>
      <div className="organization-context-controls">
        <label className="sr-only" htmlFor="organization-selector">{t('shell.organization')}</label>
        {organizations.length > 1 ? <select
          aria-label={t('shell.organization')}
          id="organization-selector"
          className="field-control"
          value={organization?.id ?? ''}
          disabled={organizations.length === 0}
          onChange={(event) => selectOrganization(event.target.value)}
        >
          <option value="">{t('shell.selectOrganization')}</option>
          {organizations.map((candidate) => (
            <option key={candidate.id} value={candidate.id}>
            {candidate.name} ({localizedStatusLabel(candidate.status ?? 'active', t)})
          </option>
          ))}
        </select> : null}
        <button
          aria-label={t('shell.refreshOrganizations')}
          className="button secondary organization-refresh"
          type="button"
          disabled={loading}
          onClick={() => void refreshOrganizations()}
        >
          {t(loading ? 'common.actions.refreshing' : 'common.actions.refresh')}
        </button>
        <LanguageSelector />
      </div>
      {error ? <small className="context-message context-error" role="alert">{error}</small> : null}
      {slowLoading && !error ? <small className="context-message" role="status">{t('shell.accessSlow')}</small> : null}
      {!loading && !error && organizations.length === 0 ? (
        <small className="context-message">
          {t('shell.noOrganizations')}
        </small>
      ) : null}
    </section>
  );
}
