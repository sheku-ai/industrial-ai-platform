'use client';

import { LocalizedText } from '../layout/LocalizedText';
import { useI18n } from '../../i18n/I18nProvider';

import { useEffect, useState } from 'react';

import { useOrganization } from '../organization/OrganizationContext';
import { OperationalHealthIssues } from './OperationalHealthIssues';
import {
  operationsApi,
  type OperationalHealth,
  type ReconciliationResponse,
} from '../../lib/operations-api';

function metricEntries(values: Record<string, number | string | null>) {
  return Object.entries(values).filter(([, value]) => typeof value === 'number');
}

export function OperationsWorkspace() {
  const { t, date } = useI18n();
  const formatDate = (value?: string | null) => date(value, { dateStyle: 'medium', timeStyle: 'short' });
  const { organization, loading: organizationLoading, error: organizationError } = useOrganization();
  const [health, setHealth] = useState<OperationalHealth | null>(null);
  const [reconciliation, setReconciliation] = useState<ReconciliationResponse | null>(null);
  const [limit, setLimit] = useState(25);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState(t('feedback.selectOrganizationForOperations'));

  const loadHealth = async (organizationId: string, organizationName: string) => {
    const snapshot = await operationsApi.health(organizationId);
    setHealth(snapshot);
    setMessage(`Operational health loaded for ${organizationName}.`);
  };

  useEffect(() => {
    setHealth(null);
    setReconciliation(null);

    if (organizationLoading) {
      setMessage(t('feedback.organizationsLoading'));
      return;
    }
    if (organizationError) {
      setMessage(organizationError);
      return;
    }
    if (!organization) {
      setMessage(t('feedback.selectOrganizationForOperations'));
      return;
    }

    const selectedOrganization = organization;
    async function load() {
      setLoading(true);
      try {
        await loadHealth(selectedOrganization.id, selectedOrganization.name);
      } catch (error) {
        setMessage(error instanceof Error ? error.message : t('feedback.operationalHealthUnavailable'));
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, [organization, organizationError, organizationLoading, t]);

  const refresh = async () => {
    if (!organization) return;
    setLoading(true);
    try {
      await loadHealth(organization.id, organization.name);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t('feedback.operationalHealthRefreshFailed'));
    } finally {
      setLoading(false);
    }
  };

  const preview = async () => {
    if (!organization) return;
    setLoading(true);
    try {
      const result = await operationsApi.previewReconciliation(organization.id, limit);
      setReconciliation(result);
      setMessage(`Preview completed: ${result.processed} item(s) evaluated.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t('feedback.reconciliationPreviewFailed'));
    } finally {
      setLoading(false);
    }
  };

  const run = async () => {
    if (!organization) return;
    const confirmed = window.confirm(
      t('dynamic.confirmReconciliation', { count: limit, organization: organization.name }),
    );
    if (!confirmed) return;

    setLoading(true);
    try {
      const result = await operationsApi.runReconciliation(
        organization.id,
        limit,
        `portal-${Date.now()}`,
      );
      setReconciliation(result);
      await loadHealth(organization.id, organization.name);
      setMessage(`Reconciliation completed: ${result.changed} changed, ${result.failed} failed.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t('feedback.reconciliationRunFailed'));
    } finally {
      setLoading(false);
    }
  };

  const organizationUnavailable = !organization || organizationLoading || Boolean(organizationError);

  return (
    <div className="builder-content">
      <section className="card">
        <h2><LocalizedText id="copy.organization_operational_status_8b02c05c" /></h2>
        {health ? (
          <>
            <p><strong><LocalizedText id="copy.status_11dc9e19" /></strong> {health.summary.overall_status}</p>
            <p><strong><LocalizedText id="copy.active_issues_905a343e" /></strong> {health.summary.active_issues}</p>
            <p><strong><LocalizedText id="copy.calculated_eb98351d" /></strong> {formatDate(health.summary.calculated_at)}</p>
            <p><strong><LocalizedText id="copy.freshness_ac8a6125" /></strong> {health.freshness.is_stale ? <LocalizedText id="copy.stale_a4e976a3" /> : <LocalizedText id="copy.current_405ab5d2" />}</p>
          </>
        ) : (
          <p><LocalizedText id="copy.no_health_snapshot_is_available_47f9e2e2" /></p>
        )}
        <button
          className="button secondary"
          type="button"
          disabled={loading || organizationUnavailable}
          onClick={() => void refresh()}
        >
          <LocalizedText id="copy.refresh_health_8237899a" /></button>
        <small className="muted-text">{message}</small>
      </section>

      {health && <OperationalHealthIssues issues={health.issues ?? []} />}

      {health && (
        <section className="grid">
          {[
            ['Scheduler', health.scheduler],
            ['Runtime', health.runtime],
            ['Artifact Publications', health.artifact_publications],
          ].map(([title, values]) => (
            <article className="card" key={title as string}>
              <h2>{title as string}</h2>
              {metricEntries(values as Record<string, number | string | null>).map(([key, value]) => (
                <p key={key}><strong>{key.replaceAll('_', ' ')}:</strong> {String(value)}</p>
              ))}
            </article>
          ))}
          <article className="card">
            <h2><LocalizedText id="copy.reconciliation_b29da9dd" /></h2>
            <p><strong><LocalizedText id="copy.candidates_6ee1e563" /></strong> {health.reconciliation.candidate_count}</p>
            <p><strong><LocalizedText id="copy.missing_feb2bbaa" /></strong> {health.reconciliation.missing_candidates}</p>
            <p><strong><LocalizedText id="copy.checksum_conflicts_37851750" /></strong> {health.reconciliation.checksum_conflict_candidates}</p>
            <p><strong><LocalizedText id="copy.oldest_candidate_03806ea9" /></strong> {formatDate(health.reconciliation.oldest_candidate_at)}</p>
          </article>
        </section>
      )}

      <section className="card">
        <h2><LocalizedText id="copy.artifact_reconciliation_784015b3" /></h2>
        <p><LocalizedText id="copy.preview_is_non_mutating_run_applies_bounded_reconcil_38536adc" /></p>
        <label className="field-label" htmlFor="reconciliation-limit"><LocalizedText id="copy.maximum_publications_7908486a" /></label>
        <input
          id="reconciliation-limit"
          className="field-control"
          type="number"
          min={1}
          max={100}
          value={limit}
          disabled={organizationUnavailable}
          onChange={(event) => setLimit(Math.min(100, Math.max(1, Number(event.target.value) || 1)))}
        />
        <button
          className="button secondary"
          type="button"
          disabled={loading || organizationUnavailable}
          onClick={() => void preview()}
        >
          <LocalizedText id="copy.preview_reconciliation_06e9d5fc" /></button>
        <button
          className="button"
          type="button"
          disabled={loading || organizationUnavailable}
          onClick={() => void run()}
        >
          <LocalizedText id="copy.run_reconciliation_29e017d8" /></button>
      </section>

      {reconciliation && (
        <section className="table-card">
          <h2><LocalizedText id="copy.reconciliation_result_a24486f4" /></h2>
          <p className="muted-text">
            <LocalizedText id="copy.mode_fbb6d6fc" />{reconciliation.mode}<LocalizedText id="copy.processed_6061e635" />{reconciliation.processed}<LocalizedText id="copy.changed_236ce262" />{reconciliation.changed}<LocalizedText id="copy.failed_0f479080" />{reconciliation.failed}
          </p>
          <table>
            <thead>
              <tr><th><LocalizedText id="copy.publication_e00441c4" /></th><th><LocalizedText id="copy.outcome_d3f06106" /></th><th><LocalizedText id="copy.changed_cb5424f6" /></th><th><LocalizedText id="copy.error_7f2f6a15" /></th></tr>
            </thead>
            <tbody>
              {reconciliation.items.map((item) => (
                <tr key={`${item.source_publication_id}-${item.outcome}`}>
                  <td><small>{item.source_publication_id}</small></td>
                  <td>{item.outcome}</td>
                  <td>{item.changed ? <LocalizedText id="copy.yes_fb360f9c" /> : <LocalizedText id="copy.no_fd128635" />}</td>
                  <td>{item.error_code ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
