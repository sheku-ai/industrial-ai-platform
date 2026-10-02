
import { useI18n } from '../../i18n/I18nProvider';

import { LocalizedText } from '../layout/LocalizedText';
import type { CapacityReadiness, CapacityVector } from '../../lib/production-readiness-api';

function text(value: unknown, fallback = 'No evidence'): string {
  if (value === null || value === undefined || value === '') return fallback;
  return String(value);
}

function issueLabel(value: Record<string, unknown>): string {
  return text(value.summary ?? value.message ?? value.code ?? value.recommended_action);
}

function VectorTable({
  configured,
  observed,
  target,
  utilization,
}: {
  configured?: CapacityVector | null;
  observed?: CapacityVector | null;
  target?: CapacityVector | null;
  utilization?: CapacityVector | null;
}) {
  const metrics: Array<keyof CapacityVector> = [
    'concurrent_requests',
    'ingestion',
    'search',
    'assistant',
    'queue',
    'worker',
    'storage',
    'database',
  ];
  return (
    <table>
      <thead>
        <tr><th><LocalizedText id="copy.capacity_45bd908d" /></th><th><LocalizedText id="status.configured" /></th><th><LocalizedText id="copy.observed_2e159b44" /></th><th><LocalizedText id="copy.target_61ad50a9" /></th><th><LocalizedText id="copy.utilization_ea3c24ad" /></th></tr>
      </thead>
      <tbody>
        {metrics.map((metric) => (
          <tr key={metric}>
            <td>{metric.replaceAll('_', ' ')}</td>
            <td>{text(configured?.[metric])}</td>
            <td>{text(observed?.[metric])}</td>
            <td>{text(target?.[metric])}</td>
            <td>{utilization ? `${(utilization[metric] * 100).toFixed(2)}%` : <LocalizedText id="copy.no_evidence_fade4ede" />}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function IssueGroup({ title, items }: { title: string; items: Record<string, unknown>[] }) {
  return (
    <article className="context-card">
      <div className="context-card-header"><strong>{title}</strong><span>{items.length}</span></div>
      {items.length ? (
        <ul className="compact-list">{items.map((item, index) => <li key={`${title}-${index}`}>{issueLabel(item)}</li>)}</ul>
      ) : <p><LocalizedText id="copy.no_persisted_items_bd7ad9cc" /></p>}
    </article>
  );
}

export function CapacityLoadSection({ capacity, error }: { capacity: CapacityReadiness | null; error?: string | null }) {
  const { t } = useI18n();
  if (error) {
    const state = error.startsWith('You do not have permission') ? 'forbidden' : 'failed';
    return (
      <section className="table-card" data-production-acceptance-section={state} data-runtime-domain="capacity">
        <h2><LocalizedText id="copy.capacity_load_779af0df" /></h2>
        <p>{error}</p>
      </section>
    );
  }
  if (!capacity) {
    return (
      <section className="table-card" data-production-acceptance-section="empty" data-runtime-domain="capacity">
        <h2><LocalizedText id="copy.capacity_load_779af0df" /></h2>
        <p><LocalizedText id="copy.persisted_capacity_evidence_is_not_available_fc11afbf" /></p>
      </section>
    );
  }
  return (
    <section className="table-card" data-production-acceptance-section="capacity-load" data-runtime-domain="capacity" data-runtime-status={capacity.status}>
      <div className="context-card-header"><h2><LocalizedText id="copy.capacity_load_779af0df" /></h2><span>{capacity.status}</span></div>
      <div className="metrics-grid">
        <article className="metric-card"><small><LocalizedText id="copy.capacity_readiness_af394b8c" /></small><strong>{capacity.status}</strong></article>
        <article className="metric-card"><small><LocalizedText id="copy.blockers_699edf83" /></small><strong>{capacity.blocker_count}</strong></article>
        <article className="metric-card"><small><LocalizedText id="copy.recommendations_4faa65b5" /></small><strong>{capacity.recommendation_count}</strong></article>
        <article className="metric-card">
          <small><LocalizedText id="copy.evidence_age_fb037192" /></small>
          <strong>{capacity.evidence_age_hours === null || capacity.evidence_age_hours === undefined ? <LocalizedText id="copy.no_evidence_fade4ede" /> : `${capacity.evidence_age_hours} hours`}</strong>
        </article>
      </div>
      <VectorTable
        configured={capacity.configured_capacity}
        observed={capacity.observed_capacity}
        target={capacity.target_capacity}
        utilization={capacity.utilization}
      />
      <div className="alerts-grid">
        <IssueGroup title={t('copy.bottlenecks_eb94872b')} items={capacity.bottlenecks} />
        <IssueGroup title={t('copy.recommendations_4faa65b5')} items={capacity.recommendations} />
        <IssueGroup title={t('copy.blockers_699edf83')} items={capacity.blockers} />
        <IssueGroup title={t('copy.warnings_1430f976')} items={capacity.warnings} />
      </div>
    </section>
  );
}
