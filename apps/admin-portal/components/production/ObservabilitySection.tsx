
import { useI18n } from '../../i18n/I18nProvider';

import { LocalizedText } from '../layout/LocalizedText';
import type { ObservabilityReadiness } from '../../lib/production-readiness-api';

function value(input: unknown, fallback = 'No evidence'): string {
  return input === null || input === undefined || input === '' ? fallback : String(input);
}

function percentage(input: number | null | undefined): string {
  return input === null || input === undefined ? 'No evidence' : `${input}%`;
}

function IssueList({ title, items }: { title: string; items: Record<string, unknown>[] }) {
  return (
    <article className="context-card">
      <div className="context-card-header"><strong>{title}</strong></div>
      {items.length ? (
        <ul className="compact-list">
          {items.map((item, index) => (
            <li key={`${title}-${index}`}>{value(item.summary ?? item.message ?? item.code)}</li>
          ))}
        </ul>
      ) : <p><LocalizedText id="copy.no_persisted_items_bd7ad9cc" /></p>}
    </article>
  );
}

export function ObservabilitySection({ observability, error }: { observability: ObservabilityReadiness | null; error?: string | null }) {
  const { t } = useI18n();
  if (error) {
    const state = error.startsWith('You do not have permission') ? 'forbidden' : 'failed';
    return (
      <section className="table-card" data-production-readiness-section={state} data-runtime-domain="observability">
        <h2><LocalizedText id="copy.observability_e2397377" /></h2>
        <p>{error}</p>
      </section>
    );
  }
  if (!observability) {
    return (
      <section className="table-card" data-production-readiness-section="empty" data-runtime-domain="observability">
        <h2><LocalizedText id="copy.observability_e2397377" /></h2>
        <p><LocalizedText id="copy.persisted_observability_evidence_is_not_available_7e344e30" /></p>
      </section>
    );
  }
  return (
    <section className="table-card" data-production-readiness-section="observability" data-runtime-domain="observability" data-runtime-status={observability.status}>
      <div className="context-card-header"><h2><LocalizedText id="copy.observability_e2397377" /></h2><span>{observability.status}</span></div>
      <div className="metrics-grid">
        <article className="metric-card"><small><LocalizedText id="copy.overall_health_b9bd879d" /></small><strong>{observability.overall_health}</strong></article>
        <article className="metric-card"><small><LocalizedText id="copy.availability_681b5b5a" /></small><strong>{observability.availability_status}</strong><span>{percentage(observability.availability_percentage)}</span></article>
        <article className="metric-card"><small><LocalizedText id="copy.freshness_5b968bd2" /></small><strong>{observability.freshness_status}</strong><span>{t('formats.durationSeconds', { count: Number(observability.evidence_age_seconds ?? 0), value: value(observability.evidence_age_seconds) })}</span></article>
        <article className="metric-card"><small><LocalizedText id="copy.coverage_80e13549" /></small><strong>{observability.coverage_status}</strong><span>{percentage(observability.signal_coverage_percentage)}</span></article>
      </div>
      <h3><LocalizedText id="copy.components_9289473e" /></h3>
      <table>
        <thead><tr><th><LocalizedText id="copy.component_c92c529e" /></th><th><LocalizedText id="common.type" /></th><th><LocalizedText id="common.status" /></th><th><LocalizedText id="copy.version_2da600bf" /></th></tr></thead>
        <tbody>
          {observability.components.map((item) => (
            <tr key={item.id}><td>{item.name}</td><td>{item.component_type}</td><td>{item.status}</td><td>{item.version}</td></tr>
          ))}
        </tbody>
      </table>
      <h3><LocalizedText id="copy.dependencies_0562f32d" /></h3>
      <table>
        <thead><tr><th><LocalizedText id="copy.dependency_ce311abe" /></th><th><LocalizedText id="common.type" /></th><th><LocalizedText id="common.status" /></th><th><LocalizedText id="copy.observed_2e159b44" /></th></tr></thead>
        <tbody>
          {observability.dependencies.map((item) => (
            <tr key={item.id}><td>{item.name}</td><td>{item.dependency_type}</td><td>{item.status}</td><td>{item.observed_at}</td></tr>
          ))}
        </tbody>
      </table>
      <h3><LocalizedText id="copy.heartbeats_33ed2d61" /></h3>
      <table>
        <thead><tr><th><LocalizedText id="copy.component_reference_5e66fbcf" /></th><th><LocalizedText id="common.status" /></th><th><LocalizedText id="copy.observed_2e159b44" /></th><th><LocalizedText id="copy.expires_a99be3da" /></th></tr></thead>
        <tbody>
          {observability.heartbeats.map((item) => (
            <tr key={item.id}><td>{item.component_id}</td><td>{item.status}</td><td>{item.observed_at}</td><td>{value(item.expires_at, 'No expiry')}</td></tr>
          ))}
        </tbody>
      </table>
      <div className="alerts-grid">
        <IssueList title={t('copy.findings_ca9b7e7e')} items={observability.findings} />
        <IssueList title={t('copy.warnings_1430f976')} items={observability.warnings} />
        <IssueList title={t('copy.blockers_699edf83')} items={observability.blockers} />
        <IssueList title={t('copy.recommendations_4faa65b5')} items={observability.recommendations} />
      </div>
    </section>
  );
}
