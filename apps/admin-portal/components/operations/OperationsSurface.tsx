'use client';

import { useMemo } from 'react';
import { useSearchParams } from 'next/navigation';

import { useI18n } from '../../i18n/I18nProvider';
import { LocalizedText } from '../layout/LocalizedText';
import { PlatformCapabilityState } from '../layout/PlatformCapabilityState';
import {
  hasOperationsEvidenceParameters,
  parseOperationsEvidenceContext,
} from '../../lib/operations-evidence-context';
import { platformCapabilityAvailable } from '../../lib/platform-dashboard-api';
import { localizedProductLabel } from '../../lib/presentation';
import { useOrganization } from '../organization/OrganizationContext';
import { OperationsCenter } from './OperationsCenter';
import { OperationsWorkspace } from './OperationsWorkspace';
import { PlatformWorkerOperations } from './PlatformWorkerOperations';

export function OperationsSurface() {
  const { t } = useI18n();
  const searchParameters = useSearchParams();
  const { navigationCapabilities, organization } = useOrganization();
  const hasEvidenceParameters = hasOperationsEvidenceParameters(searchParameters);
  const evidenceContext = useMemo(
    () => parseOperationsEvidenceContext(searchParameters),
    [searchParameters],
  );
  const evidenceContextMatchesOrganization = Boolean(
    evidenceContext && organization?.id === evidenceContext.organizationId,
  );
  const schedulerAvailable = platformCapabilityAvailable(navigationCapabilities, 'scheduler');
  return (
    <PlatformCapabilityState capability="operations">
      {(actionAvailable) => (
        <>
          {hasEvidenceParameters ? (
            <section
              className={`card operations-evidence-context${evidenceContextMatchesOrganization ? ' is-selected' : ' is-empty'}`}
              data-evidence-context-state={evidenceContextMatchesOrganization ? 'selected' : 'unavailable'}
            >
              <span className="badge">{t('governanceUx.reviewEvidence')}</span>
              <h2>{evidenceContext?.controlId ?? t('governanceUx.items.unknown')}</h2>
              {evidenceContextMatchesOrganization && evidenceContext ? (
                <>
                  <p>{organization?.name}</p>
                  <dl className="technical-details-grid">
                    <dt>{t('governanceUx.technicalCode')}</dt><dd className="technical-value">{evidenceContext.controlId}</dd>
                    <dt>{t('copy.domain_9b10914d')}</dt><dd>{localizedProductLabel(evidenceContext.domain, t)}</dd>
                    <dt>{t('common.status')}</dt><dd>{localizedProductLabel(evidenceContext.status, t)}</dd>
                  </dl>
                </>
              ) : (
                <p>{t(evidenceContext ? 'errors.notFound' : 'errors.validation')}</p>
              )}
              <a className="button secondary" href="/operations">{t('common.actions.close')}</a>
            </section>
          ) : null}
          <section className="administration-grid">
            <a className="administration-destination" href="/runtime"><span><LocalizedText id="copy.execution_runtime_76094501" /></span><p><LocalizedText id="copy.inspect_executions_attempts_leases_and_failures_4cf946ae" /></p><small><LocalizedText id="copy.open_6f4789b0" /></small></a>
            {schedulerAvailable ? <a className="administration-destination" href="/scheduler"><span><LocalizedText id="copy.scheduler_background_services_8e0f38e9" /></span><p><LocalizedText id="copy.review_jobs_schedules_and_background_processing_560e3629" /></p><small><LocalizedText id="copy.open_6f4789b0" /></small></a> : <span aria-disabled="true" className="administration-destination is-disabled"><span><LocalizedText id="copy.scheduler_background_services_8e0f38e9" /></span><p><LocalizedText id="copy.access_required_3d2f1a2e" /></p></span>}
          </section>
          <div className="product-workspace">
            <details className="advanced-panel" open={hasEvidenceParameters}><summary><LocalizedText id="copy.operational_health_and_issues_3c9a3a99" /></summary><div className="advanced-panel-content"><OperationsCenter evidenceContext={evidenceContextMatchesOrganization ? evidenceContext : null} /></div></details>
            {actionAvailable ? <details className="advanced-panel"><summary><LocalizedText id="copy.runtime_diagnostics_310a821b" /></summary><div className="advanced-panel-content"><OperationsWorkspace /></div></details> : null}
            {actionAvailable ? <details className="advanced-panel"><summary><LocalizedText id="copy.worker_controls_d93681b0" /></summary><div className="advanced-panel-content"><PlatformWorkerOperations /></div></details> : null}
          </div>
        </>
      )}
    </PlatformCapabilityState>
  );
}
