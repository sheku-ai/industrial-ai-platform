'use client';

import { LocalizedText } from '../layout/LocalizedText';
import { useI18n } from '../../i18n/I18nProvider';

import { useEffect, useMemo, useState } from 'react';

import {
  getProductIntegrationRuntime,
  type ProductIntegrationRuntime,
} from '../../lib/product-integration-api';
import { localizedProductLabel, productLabel } from '../../lib/presentation';

function asText(value: unknown, fallback = '-'): string {
  if (value === null || value === undefined || value === '') return fallback;
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

function asTextList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)) : [];
}

function displayText(value: unknown, fallback = '-'): string {
  return typeof value === 'string' ? productLabel(value, fallback) : asText(value, fallback);
}

function statusClass(ready: boolean): string {
  return ready ? 'status-dot ready' : 'status-dot degraded';
}

function issueText(item: Record<string, unknown>, translate: (key: string) => string): string {
  return displayText(item.message ?? item.label ?? item.reason ?? item.code, translate('dynamic.detailsAvailable'));
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

function PlatformSummary({ runtime }: { runtime: ProductIntegrationRuntime }) {
  const { t } = useI18n();
  const platform = runtime.platform ?? {};
  const overall = runtime.overall ?? {};
  const score = runtime.product_score ?? {};
  const acceptance = runtime.product_acceptance ?? {};
  const freshness = runtime.evidence_freshness ?? {};
  const eligibility = runtime.release_eligibility ?? {};
  return (
    <section className="grid" data-product-integration-section="platform-summary">
      <article className="card health-card">
        <div className="context-card-header">
          <h2><LocalizedText id="copy.domain_integration_readiness_c72f02a9" /></h2>
          <span className={statusClass(Boolean(overall.domain_integration_ready))}></span>
        </div>
        <span className="metric-value">{overall.domain_integration_ready ? <LocalizedText id="status.ready" /> : <LocalizedText id="copy.not_ready_2b50ff80" />}</span>
      </article>
      <article className="card health-card">
        <div className="context-card-header">
          <h2><LocalizedText id="copy.overall_release_eligibility_3f160534" /></h2>
          <span className={statusClass(Boolean(eligibility.eligible))}></span>
        </div>
        <span className="metric-value">{eligibility.eligible ? <LocalizedText id="copy.eligible_3e7a6e9c" /> : displayText(eligibility.status, 'Unavailable')}</span>
      </article>
      <article className="card health-card">
        <div className="context-card-header">
          <h2><LocalizedText id="copy.product_acceptance_0826d08b" /></h2>
          <span className={statusClass(acceptance.status === 'passed')}></span>
        </div>
        <span className="metric-value">{displayText(acceptance.status, 'Unavailable')}</span>
      </article>
      <article className="card health-card">
        <div className="context-card-header">
          <h2><LocalizedText id="copy.evidence_freshness_56563eff" /></h2>
          <span className={statusClass(freshness.status === 'current')}></span>
        </div>
        <span className="metric-value">{displayText(freshness.status, 'Unavailable')}</span>
      </article>
      <MetricCard label={t('copy.platform_version_a492452f')} value={platform.platform_version} />
      <MetricCard label={t('copy.platform_stage_f55cd4af')} value={platform.platform_stage} />
      <MetricCard label={t('copy.workspaces_205b4561')} value={platform.workspace_count} />
      <MetricCard label={t('copy.pending_workspaces_869e866b')} value={platform.pending_workspace_count} />
      <MetricCard label={t('copy.integration_score_4c32e70c')} value={score.overall_score} />
    </section>
  );
}

function IntegrationCheckCoverage({ runtime }: { runtime: ProductIntegrationRuntime }) {
  const { t } = useI18n();
  const domains = [
    [t('navigation.administration'), runtime.administration],
    [t('navigation.documents'), runtime.documents],
    [t('navigation.knowledge'), runtime.knowledge],
    [t('dynamic.assistants'), runtime.assistants],
    [t('navigation.operations'), runtime.operations],
    [t('navigation.governance'), runtime.governance],
    [t('dynamic.connectors'), runtime.connectors],
    [t('dynamic.aiStudio'), runtime.ai_studio],
  ];
  return (
    <section className="table-card" data-product-integration-section="integration-check-coverage">
      <h2><LocalizedText id="copy.integration_check_coverage_bec3f258" /></h2>
      <p><LocalizedText id="copy.coverage_includes_all_reported_checks_domain_readine_bc0b66d0" /></p>
      <table>
        <thead>
          <tr><th><LocalizedText id="copy.domain_9b10914d" /></th><th><LocalizedText id="copy.checks_satisfied_ec348926" /></th><th><LocalizedText id="copy.checks_evaluated_7e09f3ee" /></th><th><LocalizedText id="copy.coverage_80e13549" /></th></tr>
        </thead>
        <tbody>
          {domains.map(([label, value]) => {
            const section = asRecord(value);
            const checks = Object.values(section);
            const ready = checks.filter(Boolean).length;
            const total = checks.length;
            return (
              <tr key={label as string}>
                <td>{label as string}</td>
                <td>{ready}</td>
                <td>{total}</td>
                <td><span className={statusClass(total > 0 && ready === total)}></span>{t('dynamic.checksSatisfied', { ready, total })}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

function WorkspaceReadiness({ validation }: { validation: Record<string, unknown> }) {
  return (
    <section className="table-card" data-product-integration-section="workspace-readiness">
      <h2><LocalizedText id="copy.workspace_readiness_14d888ed" /></h2>
      <table>
        <thead>
          <tr><th><LocalizedText id="copy.workspace_4ca0a75c" /></th><th><LocalizedText id="copy.path_519e3913" /></th><th><LocalizedText id="copy.reachable_fa887b56" /></th><th><LocalizedText id="copy.runtime_c4740e4c" /></th><th><LocalizedText id="copy.diagnostics_3af2279f" /></th></tr>
        </thead>
        <tbody>
          {asList(validation.workspaces).map((workspace) => (
            <tr key={asText(workspace.key)}>
              <td>{asText(workspace.label)}</td>
              <td><small>{asText(workspace.path)}</small></td>
              <td>{asText(workspace.reachable)}</td>
              <td>{asText(workspace.runtime_ready)}</td>
              <td>{asText(workspace.diagnostics_ready)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function RCGate({ gate }: { gate: Record<string, unknown> }) {
  const { t } = useI18n();
  return (
    <section className="table-card" data-product-integration-section="rc-gate">
      <h2><LocalizedText id="copy.overall_release_eligibility_ea4f5564" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.release_status_52914199')} value={gate.release_eligibility_status ?? t('copy.unavailable_1d5ee313')} />
        <MetricCard label={t('copy.domain_integration_2bf24514')} value={gate.domain_integration_ready ? t('status.ready') : t('copy.not_ready_2b50ff80')} />
        <MetricCard label={t('copy.required_domains_ready_827e794f')} value={gate.required_domains_ready} />
        <MetricCard label={t('copy.optional_domains_non_blocking_4a7f36ec')} value={gate.optional_domains_non_blocking} />
        <MetricCard label={t('copy.side_effect_free_d6e179bb')} value={gate.side_effect_free} />
        <MetricCard label={t('copy.external_calls_free_08335869')} value={gate.external_calls_free} />
        <MetricCard label={t('copy.ai_execution_free_a777b028')} value={gate.ai_execution_free} />
      </div>
      <p>{displayText(gate.release_eligibility_reason, 'Current Product Acceptance evidence is required.')}</p>
      {asTextList(gate.release_eligibility_blocking_reasons).length > 0 ? (
        <p><LocalizedText id="copy.release_blockers_8f594d63" />{asTextList(gate.release_eligibility_blocking_reasons).map((reason) => localizedProductLabel(reason, t)).join(', ')}</p>
      ) : null}
    </section>
  );
}

function DomainStatus({ readiness }: { readiness: Record<string, unknown> }) {
  return (
    <section className="table-card" data-product-integration-section="domain-status">
      <h2><LocalizedText id="copy.domain_readiness_classification_c956bd7c" /></h2>
      <p><LocalizedText id="copy.this_classification_represents_required_domain_check_34e0a51a" /></p>
      <table>
        <thead>
          <tr><th><LocalizedText id="copy.domain_9b10914d" /></th><th><LocalizedText id="copy.required_eed6bfb4" /></th><th><LocalizedText id="common.status" /></th><th><LocalizedText id="copy.score_489f4877" /></th><th><LocalizedText id="copy.blocking_d785c0d4" /></th><th><LocalizedText id="copy.reason_f219cc06" /></th></tr>
        </thead>
        <tbody>
          {asList(readiness.all_domains).map((domain) => (
            <tr key={asText(domain.domain)}>
              <td>{displayText(domain.domain)}</td>
              <td>{asText(domain.required)}</td>
              <td>{displayText(domain.status)}</td>
              <td>{asText(domain.score, '0')}</td>
              <td>{asText(domain.blocking)}</td>
              <td>{displayText(domain.reason)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function ReferenceTenant({ reference }: { reference: Record<string, unknown> }) {
  const { t } = useI18n();
  return (
    <section className="table-card" data-product-integration-section="reference-tenant">
      <h2><LocalizedText id="copy.reference_tenant_639d1ca4" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.tenant_ready_cc00ad3f')} value={reference.reference_tenant_ready} />
        <MetricCard label={t('copy.documents_ready_0b568a29')} value={reference.reference_documents_ready} />
        <MetricCard label={t('copy.knowledge_ready_c9c7f17a')} value={reference.reference_knowledge_ready} />
        <MetricCard label={t('copy.search_ready_028329ac')} value={reference.reference_search_ready} />
        <MetricCard label={t('copy.chat_ready_a5697bb5')} value={reference.reference_chat_ready} />
      </div>
    </section>
  );
}

function IntegrationMatrix({ matrix }: { matrix: Record<string, unknown> }) {
  return (
    <section className="table-card" data-product-integration-section="integration-matrix">
      <h2><LocalizedText id="copy.integration_matrix_c8b33363" /></h2>
      <table>
        <thead>
          <tr><th><LocalizedText id="copy.domain_9b10914d" /></th><th><LocalizedText id="common.status" /></th><th><LocalizedText id="status.ready" /></th></tr>
        </thead>
        <tbody>
          {asList(matrix.domains).map((item) => (
            <tr key={asText(item.domain)}>
              <td>{asText(item.domain)}</td>
              <td>{displayText(item.status)}</td>
              <td>{asText(item.ready)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function ProductScore({ score }: { score: Record<string, unknown> }) {
  return (
    <section className="table-card" data-product-integration-section="product-score">
      <h2><LocalizedText id="copy.product_score_4c184913" /></h2>
      <div className="metrics-grid">
        {Object.entries(score).map(([key, value]) => (
          <MetricCard key={key} label={key.replaceAll('_', ' ')} value={value} />
        ))}
      </div>
    </section>
  );
}

function Diagnostics({ runtime }: { runtime: ProductIntegrationRuntime }) {
  const { t } = useI18n();
  const diagnostics = runtime.diagnostics ?? {};
  const rcGate = asRecord(runtime.rc_gate);
  const groups = [
    ['Domain integration blockers', diagnostics.blocking_issues ?? []],
    ['Warnings', diagnostics.warnings ?? []],
    ['Pending Capabilities', diagnostics.pending_capabilities ?? []],
    ['Recommendations', diagnostics.recommendations ?? []],
    ['Normalization Debt', asList(rcGate.normalization_debt)],
  ];
  return (
    <section className="table-card" data-product-integration-section="diagnostics">
      <h2><LocalizedText id="copy.domain_integration_diagnostics_09e3ce0a" /></h2>
      <p><LocalizedText id="copy.blocker_counts_in_this_section_apply_only_to_domain__b871dd8c" /></p>
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

export function ProductIntegrationWorkspace() {
  const { t } = useI18n();
  const [runtime, setRuntime] = useState<ProductIntegrationRuntime | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const payload = await getProductIntegrationRuntime();
        if (!cancelled) setRuntime(payload);
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : t('feedback.productIntegrationRuntimeUnavailable'));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [t]);

  const workspaceValidation = useMemo(() => asRecord(runtime?.workspace_validation), [runtime]);
  const domainReadiness = useMemo(() => asRecord(runtime?.domain_readiness), [runtime]);
  const rcGate = useMemo(() => asRecord(runtime?.rc_gate), [runtime]);

  if (loading) {
    return (
      <section className="card" data-product-integration-section="loading">
        <h2><LocalizedText id="copy.loading_product_integration_review_03b322cc" /></h2>
        <p><LocalizedText id="copy.retrieving_product_readiness_from_postgresql_backed__7d1b7655" /></p>
      </section>
    );
  }

  if (error || !runtime) {
    return (
      <section className="card" data-product-integration-section="error">
        <h2><LocalizedText id="copy.product_integration_review_unavailable_63675f54" /></h2>
        <p>{error ?? <LocalizedText id="copy.no_product_integration_runtime_payload_was_returned_52ec0c90" />}</p>
      </section>
    );
  }

  return (
    <div className="platform-home" data-product-integration="ready">
      <header className="platform-hero" data-product-integration-section="production-readiness">
        <div>
          <span className="badge"><LocalizedText id="pages.product.title" /></span>
          <h2><LocalizedText id="copy.product_integration_overview_4070b97b" /></h2>
          <p><LocalizedText id="copy.domain_integration_readiness_and_the_separate_releas_d99e1ef5" /></p>
        </div>
        <div className="platform-status-panel">
          <p><span className={statusClass(runtime.runtime_status === 'ready')}></span> <LocalizedText id="copy.runtime_c4740e4c" />{displayText(runtime.runtime_status)}</p>
          <p><LocalizedText id="copy.domain_integration_2f788ce3" />{runtime.overall.domain_integration_ready ? <LocalizedText id="status.ready" /> : <LocalizedText id="copy.not_ready_2b50ff80" />}</p>
          <p><LocalizedText id="copy.release_eligibility_fa234e86" />{displayText(runtime.release_eligibility.status, 'Unavailable')}</p>
          <p><LocalizedText id="copy.postgresql_source_602da08d" />{asText(runtime.postgresql_source_of_truth)}</p>
          <p><LocalizedText id="copy.side_effects_8b6f4c47" />{asText(runtime.side_effects_performed)}</p>
        </div>
      </header>

      <PlatformSummary runtime={runtime} />
      <RCGate gate={rcGate} />
      <DomainStatus readiness={domainReadiness} />
      <WorkspaceReadiness validation={workspaceValidation} />
      <IntegrationCheckCoverage runtime={runtime} />
      <ReferenceTenant reference={runtime.reference_tenant} />
      <IntegrationMatrix matrix={runtime.readiness_matrix} />
      <ProductScore score={runtime.product_score} />
      <Diagnostics runtime={runtime} />
    </div>
  );
}
