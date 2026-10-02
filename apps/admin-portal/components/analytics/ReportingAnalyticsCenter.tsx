'use client';

import { LocalizedText } from '../layout/LocalizedText';
import { useI18n } from '../../i18n/I18nProvider';

import { useEffect, useState } from 'react';

import {
  getReportingAnalyticsRuntime,
  type ReportingAnalyticsRuntime,
} from '../../lib/reporting-analytics-api';
import { platformCapabilityAvailable } from '../../lib/platform-dashboard-api';
import { localizedProductLabel, productLabel } from '../../lib/presentation';
import { useOrganization } from '../organization/OrganizationContext';

type PlatformOperationsAccessState = 'available' | 'checking' | 'restricted';

function asText(value: unknown, fallback = '-'): string {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'boolean') return value ? 'Available' : 'Unavailable';
  if (typeof value === 'string' && /^[a-z0-9]+(?:_[a-z0-9]+)+$/.test(value)) return productLabel(value, fallback);
  return String(value);
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function asList(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item) => item && typeof item === 'object') as Record<string, unknown>[]
    : [];
}

function statusClass(ready: boolean): string {
  return ready ? 'status-dot ready' : 'status-dot degraded';
}

function issueText(item: Record<string, unknown>, translate: (key: string) => string): string {
  return asText(item.message ?? item.label ?? item.reason ?? item.code, translate('dynamic.detailsAvailable'));
}

function MetricCard({ label, value }: { label: string; value: unknown }) {
  const { t } = useI18n();
  return (
    <article className="metric-card">
      <small>{label}</small>
      <strong>{localizedProductLabel(value, t, '0')}</strong>
    </article>
  );
}

function Summary({ runtime }: { runtime: ReportingAnalyticsRuntime }) {
  const { t } = useI18n();
  const summary = runtime.workspace_summary ?? {};
  const platform = runtime.platform_summary ?? {};
  return (
    <section className="grid" data-reporting-section="summary">
      <article className="card health-card">
        <div className="context-card-header">
          <h2><LocalizedText id="copy.analytics_center_f2dcc4f6" /></h2>
          <span className={statusClass(Boolean(summary.analytics_ready))}></span>
        </div>
        <span className="metric-value">{localizedProductLabel(runtime.runtime_status, t)}</span>
      </article>
      <MetricCard label={t('copy.product_score_fde6a9c9')} value={summary.overall_product_score} />
      <MetricCard label={t('copy.baseline_e6ab7982')} value={platform.product_baseline_status} />
      <MetricCard label={t('copy.integration_ready_c04b1186')} value={platform.integration_ready} />
      <MetricCard label={t('copy.production_candidate_3af50433')} value={platform.production_candidate} />
      <MetricCard label={t('copy.postgresql_source_33bab8bf')} value={summary.postgresql_source_of_truth} />
      <MetricCard label={t('copy.llm_used_2f2d3965')} value={summary.llm_used} />
      <MetricCard label={t('copy.qdrant_used_71ab4e52')} value={summary.qdrant_used} />
    </section>
  );
}

function ExecutiveKpis({ runtime }: { runtime: ReportingAnalyticsRuntime }) {
  const { t } = useI18n();
  const kpis = runtime.executive_kpis ?? {};
  return (
    <section className="table-card" data-reporting-section="executive-kpis">
      <h2><LocalizedText id="copy.executive_kpis_f64c8855" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.registered_documents_96f5720c')} value={kpis.registered_documents} />
        <MetricCard label={t('copy.knowledge_documents_e25dbfc5')} value={kpis.knowledge_documents} />
        <MetricCard label={t('copy.knowledge_chunks_99e06082')} value={kpis.knowledge_chunks} />
        <MetricCard label={t('copy.indexed_documents_21aeb5c3')} value={kpis.indexed_documents} />
        <MetricCard label={t('copy.indexed_chunks_86bc1069')} value={kpis.indexed_chunks} />
        <MetricCard label={t('copy.search_requests_f13d828f')} value={kpis.search_requests} />
        <MetricCard label={t('copy.assistant_requests_112d955b')} value={kpis.assistant_requests} />
        <MetricCard label={t('copy.conversations_07c59b44')} value={kpis.conversation_count} />
        <MetricCard label={t('dynamic.connectors')} value={kpis.connector_count} />
        <MetricCard label={t('copy.scheduler_jobs_6c51daaf')} value={kpis.scheduler_jobs} />
        <MetricCard label={t('copy.background_services_7ded584b')} value={kpis.background_services} />
        <MetricCard label={t('copy.runtime_executions_dd145dc5')} value={kpis.runtime_executions} />
        <MetricCard label={t('copy.feedback_c8d7677e')} value={kpis.feedback_count} />
        <MetricCard label={t('copy.audit_events_9e7d8c07')} value={kpis.audit_events} />
        <MetricCard label={t('copy.reference_tenant_a04947d9')} value={kpis.reference_tenant_status} />
      </div>
    </section>
  );
}

function ProductUsage({
  runtime,
  operationsAccess,
}: {
  runtime: ReportingAnalyticsRuntime;
  operationsAccess: PlatformOperationsAccessState;
}) {
  const { t } = useI18n();
  const kpis = runtime.executive_kpis ?? {};
  const diagnostics = runtime.diagnostics ?? {};
  const attention = runtime.warnings.length + asList(diagnostics.blocking_issues).length;
  return (
    <section className="table-card" data-reporting-section="product-usage">
      <div className="section-header"><span className="eyebrow"><LocalizedText id="copy.selected_organization_all_time_dc81bcf1" /></span><h2><LocalizedText id="copy.operational_product_activity_c590930a" /></h2><p><LocalizedText id="copy.persisted_activity_for_the_active_organization_platf_97448061" /></p></div>
      <div className="report-domain-grid">
        <article><h3><LocalizedText id="pages.documents.title" /></h3><strong>{asText(kpis.registered_documents, '0')}</strong><p>{t('dynamic.searchableDocumentCount', { count: Number(kpis.indexed_documents ?? 0), value: asText(kpis.indexed_documents, '0') })}</p><a className="text-link" href="/documents"><LocalizedText id="copy.open_documents_30f1108c" /></a></article>
        <article><h3><LocalizedText id="copy.search_activity_4fb33935" /></h3><strong>{asText(kpis.search_requests, '0')}</strong><p><LocalizedText id="copy.governed_searches_in_this_organization_6d660358" /></p><a className="text-link" href="/search"><LocalizedText id="copy.open_search_a291d5a1" /></a></article>
        <article><h3><LocalizedText id="copy.assistant_executions_4ad21503" /></h3><strong>{asText(kpis.assistant_requests, '0')}</strong><p>{t('dynamic.persistedConversationCount', { count: Number(kpis.conversation_count ?? 0), value: asText(kpis.conversation_count, '0') })}</p><a className="text-link" href="/ask"><LocalizedText id="copy.open_ask_ai_40e44973" /></a></article>
        <article>
          <h3><LocalizedText id="copy.technical_review_1bec99d8" /></h3>
          <strong>{attention}</strong>
          <p><LocalizedText id="copy.platform_or_release_findings_in_advanced_scope_8284f71a" /></p>
          {operationsAccess === 'available' ? (
            <a className="text-link" href="/operations"><LocalizedText id="copy.open_platform_operations_6ba5ed72" /></a>
          ) : (
            <small aria-disabled="true" className="report-access-note">
              {t(operationsAccess === 'checking' ? 'copy.checking_access_c5108c02' : 'navigation.platformPermissionRequired')}
            </small>
          )}
        </article>
      </div>
    </section>
  );
}

function ReadinessScores({ runtime }: { runtime: ReportingAnalyticsRuntime }) {
  const { t } = useI18n();
  const scores = runtime.readiness_scores ?? {};
  return (
    <section className="table-card" data-reporting-section="readiness">
      <h2><LocalizedText id="copy.readiness_scores_bc624689" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.overall_product_0b8037e1')} value={scores.overall_product_score} />
        <MetricCard label={t('navigation.operations')} value={scores.operational_score} />
        <MetricCard label={t('pages.knowledge.title')} value={scores.knowledge_score} />
        <MetricCard label={t('ask.assistant')} value={scores.assistant_score} />
        <MetricCard label={t('copy.security_f25ce1b8')} value={scores.security_score} />
        <MetricCard label={t('copy.workflow_d7a48414')} value={scores.workflow_score} />
        <MetricCard label={t('copy.scheduler_cdcb4d84')} value={scores.scheduler_score} />
        <MetricCard label={t('pages.governance.title')} value={scores.governance_score} />
      </div>
    </section>
  );
}

function AnalyticsSections({ runtime }: { runtime: ReportingAnalyticsRuntime }) {
  const sections = [
    ['Documents', runtime.document_analytics],
    ['Knowledge', runtime.knowledge_analytics],
    ['Enterprise Search', runtime.enterprise_search_analytics],
    ['Assistants', runtime.assistant_analytics],
    ['Conversations', runtime.conversation_analytics],
    ['Workflows', runtime.workflow_analytics],
    ['Scheduler', runtime.scheduler_analytics],
    ['Background Services', runtime.background_services_analytics],
    ['Connectors', runtime.connector_analytics],
    ['Security', runtime.security_analytics],
    ['Governance', runtime.governance_analytics],
    ['Audit', runtime.audit_analytics],
    ['Feedback', runtime.feedback_analytics],
    ['Reference Tenant', runtime.reference_tenant_analytics],
  ];
  return (
    <section className="table-card" data-reporting-section="analytics-sections">
      <h2><LocalizedText id="copy.analytics_sections_54e0fdc0" /></h2>
      <table>
        <thead>
          <tr><th><LocalizedText id="copy.section_f2c6b564" /></th><th><LocalizedText id="common.status" /></th><th><LocalizedText id="copy.primary_metrics_2acd939c" /></th></tr>
        </thead>
        <tbody>
          {sections.map(([label, payload]) => {
            const item = asRecord(payload);
            const status = asRecord(item.summary).runtime_status
              ?? item.reference_tenant_status
              ?? item.pipeline_health;
            return (
              <tr key={label as string}>
                <td>{label as string}</td>
                <td>{asText(status)}</td>
                <td><small>{Object.keys(item).slice(0, 8).join(', ')}</small></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

function Trends({ runtime }: { runtime: ReportingAnalyticsRuntime }) {
  const trendGroups = [
    ['Product readiness', runtime.product_readiness_trends],
    ['Runtime health', runtime.runtime_health_trends],
    ['Operational trends', runtime.operational_trends],
  ];
  return (
    <section className="table-card" data-reporting-section="trends">
      <h2><LocalizedText id="copy.trends_716f3fa8" /></h2>
      <table>
        <thead>
          <tr><th><LocalizedText id="copy.group_171a0606" /></th><th><LocalizedText id="copy.metric_b2bb7604" /></th><th><LocalizedText id="copy.current_4fc0e2bc" /></th><th><LocalizedText id="copy.historical_bb2fe205" /></th><th><LocalizedText id="copy.direction_fd8e45ba" /></th><th><LocalizedText id="copy.growth_f3b21e04" /></th></tr>
        </thead>
        <tbody>
          {trendGroups.flatMap(([group, payload]) =>
            asList(asRecord(payload).items).map((item) => (
              <tr key={`${group}-${asText(item.key)}`}>
                <td>{group as string}</td>
                <td>{asText(item.label)}</td>
                <td>{asText(item.current_snapshot)}</td>
                <td>{asText(item.historical_snapshot)}</td>
                <td>{asText(item.trend_direction)}</td>
                <td>{asText(item.growth)}</td>
              </tr>
            )),
          )}
        </tbody>
      </table>
    </section>
  );
}

function Diagnostics({ runtime }: { runtime: ReportingAnalyticsRuntime }) {
  const { t } = useI18n();
  const diagnostics = runtime.diagnostics ?? {};
  const groups = [
    ['Warnings', runtime.warnings],
    ['Recommendations', runtime.recommendations],
    ['Pending capabilities', asList(diagnostics.pending_capabilities)],
    ['Blocking issues', asList(diagnostics.blocking_issues)],
  ];
  return (
    <section className="table-card" data-reporting-section="diagnostics">
      <h2><LocalizedText id="copy.diagnostics_and_recommendations_7b1d9943" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.side_effects_f9b9f592')} value={runtime.side_effects_performed} />
        <MetricCard label={t('copy.external_calls_2326bb0c')} value={runtime.external_calls_performed} />
        <MetricCard label={t('copy.llm_used_2f2d3965')} value={runtime.llm_used} />
        <MetricCard label={t('copy.qdrant_used_71ab4e52')} value={runtime.qdrant_used} />
      </div>
      <div className="alerts-grid">
        {groups.map(([label, values]) => (
          <article className="context-card" key={label as string}>
            <div className="context-card-header">
              <strong>{label as string}</strong>
              <span>{(values as Record<string, unknown>[]).length}</span>
            </div>
            {(values as Record<string, unknown>[]).length > 0 ? (
              <ul className="compact-list">
                {(values as Record<string, unknown>[]).slice(0, 8).map((item, index) => (
                  <li key={`${label}-${index}`}>{issueText(item, t)}</li>
                ))}
              </ul>
            ) : (
              <p><LocalizedText id="common.noItems" /></p>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

export function ReportingAnalyticsCenter() {
  const { t } = useI18n();
  const {
    capabilitiesLoading,
    capabilitiesResolved,
    navigationCapabilities,
  } = useOrganization();
  const [runtime, setRuntime] = useState<ReportingAnalyticsRuntime | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const operationsAccess: PlatformOperationsAccessState = capabilitiesLoading || !capabilitiesResolved
    ? 'checking'
    : platformCapabilityAvailable(navigationCapabilities, 'operations')
      ? 'available'
      : 'restricted';

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const payload = await getReportingAnalyticsRuntime();
        if (!cancelled) setRuntime(payload);
      } catch (loadError) {
        if (!cancelled) {
          setError(
            loadError instanceof Error
              ? loadError.message
              : t('feedback.reportingAnalyticsUnavailable'),
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [reloadToken, t]);

  if (loading) {
    return (
      <section className="card workspace-state" data-reporting-section="loading" role="status">
        <span className="eyebrow"><LocalizedText id="copy.reporting_analytics_5f653165" /></span>
        <h2><LocalizedText id="copy.evaluating_platform_evidence_25a27447" /></h2>
        <p><LocalizedText id="copy.evaluating_platform_evidence_this_may_take_a_few_sec_5515fca1" /></p>
        <div className="metrics-grid" aria-hidden="true">
          {[t('copy.operational_product_activity_c590930a'), t('pages.search.title'), t('pages.ask.title'), t('pages.production.title')].map((label) => (
            <article className="metric-card" key={label}><small>{label}</small><strong>—</strong></article>
          ))}
        </div>
      </section>
    );
  }

  if (error || !runtime) {
    return (
      <section className="card" data-reporting-section="error">
        <h2><LocalizedText id="copy.reporting_analytics_unavailable_0e619525" /></h2>
        <p>{error ?? <LocalizedText id="copy.no_reporting_analytics_runtime_payload_was_returned_09bf932e" />}</p>
        <button className="button secondary" type="button" onClick={() => setReloadToken((value) => value + 1)}><LocalizedText id="common.actions.retry" /></button>
      </section>
    );
  }

  return (
    <div className="product-workspace">
      <ProductUsage operationsAccess={operationsAccess} runtime={runtime} />
      <details className="advanced-panel"><summary><LocalizedText id="copy.advanced_analytics_and_readiness_evidence_7b94d3aa" /></summary><div className="advanced-panel-content"><Summary runtime={runtime} /><ExecutiveKpis runtime={runtime} /><ReadinessScores runtime={runtime} /><AnalyticsSections runtime={runtime} /><Trends runtime={runtime} /><Diagnostics runtime={runtime} /></div></details>
    </div>
  );
}
