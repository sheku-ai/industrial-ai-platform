'use client';

import { localizedProductLabel } from '../../lib/presentation';

import { useI18n } from '../../i18n/I18nProvider';

import { LocalizedText } from '../layout/LocalizedText';

import { useEffect, useState } from 'react';

import {
  getWorkflowStudioRuntime,
  type WorkflowStudioRuntime,
} from '../../lib/workflow-studio-api';

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

function Summary({ runtime }: { runtime: WorkflowStudioRuntime }) {
  const { t } = useI18n();
  const summary = runtime.workspace_summary ?? {};
  const readiness = runtime.workflow_readiness ?? {};
  return (
    <section className="grid" data-workflow-studio-section="summary">
      <article className="card health-card">
        <div className="context-card-header">
          <h2><LocalizedText id="pages.workflows.title" /></h2>
          <span className={statusClass(Boolean(summary.workflow_studio_ready))}></span>
        </div>
        <span className="metric-value">{asText(readiness.overall_workflow_readiness)}</span>
      </article>
      <MetricCard label={t('copy.capability_score_24416f84')} value={readiness.workflow_score} />
      <MetricCard label={t('copy.available_capabilities_209bd55a')} value={readiness.ready_workflows} />
      <MetricCard label={t('copy.capabilities_needing_attention_9c11e2cf')} value={readiness.degraded_workflows} />
      <MetricCard label={t('copy.optional_capabilities_8895ea63')} value={readiness.optional_workflows} />
      <MetricCard label={t('copy.blocked_capabilities_c41657f4')} value={readiness.blocked_workflows} />
      <MetricCard label={t('copy.reference_tenant_a04947d9')} value={summary.reference_tenant_ready} />
      <MetricCard label={t('copy.postgresql_source_33bab8bf')} value={summary.postgresql_source_of_truth} />
    </section>
  );
}

function WorkflowInventory({ runtime }: { runtime: WorkflowStudioRuntime }) {
  const { t } = useI18n();
  return (
    <section className="table-card" data-workflow-studio-section="inventory">
      <div className="section-header"><div><span className="eyebrow"><LocalizedText id="copy.platform_inventory_23d82054" /></span><h2><LocalizedText id="copy.available_capabilities_209bd55a" /></h2><p><LocalizedText id="copy.this_inventory_reports_platform_capabilities_and_the_3eac4f0f" /></p></div></div>
      <table>
        <thead>
          <tr>
            <th><LocalizedText id="common.name" /></th>
            <th><LocalizedText id="copy.category_a3c686e7" /></th>
            <th><LocalizedText id="copy.availability_681b5b5a" /></th>
            <th><LocalizedText id="copy.scope_4651a34e" /></th>
            <th><LocalizedText id="common.type" /></th>
            <th><LocalizedText id="common.status" /></th>
            <th><LocalizedText id="common.description" /></th>
          </tr>
        </thead>
        <tbody>
          {runtime.workflow_inventory.map((workflow) => {
            const evidence = asRecord(workflow.runtime_evidence);
            const dependencies = Array.isArray(workflow.dependencies)
              ? workflow.dependencies.map((dependency) => localizedProductLabel(dependency, t)).join(', ')
              : '';
            return (
              <tr key={asText(workflow.workflow_key)}>
                <td>{asText(workflow.workflow_name)}</td>
                <td>{localizedProductLabel(workflow.category, t)}</td>
                <td>{workflow.status === 'ready' ? <LocalizedText id="copy.available_7c62a142" /> : workflow.optional ? <LocalizedText id="copy.optional_not_configured_4a1ffd22" /> : <LocalizedText id="copy.needs_platform_setup_d28f1880" />}</td>
                <td><LocalizedText id="pages.workflows.section" /></td>
                <td>{workflow.optional ? <LocalizedText id="copy.optional_0c6c4102" /> : <LocalizedText id="copy.core_68836c55" />}</td>
                <td>{localizedProductLabel(workflow.status, t)}</td>
                <td>{dependencies
                  ? t('dynamic.dependsOn', { dependencies })
                  : t('dynamic.runtimeEvidence', { evidence: localizedProductLabel(evidence.source, t, t('dynamic.notYetReported')) })}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

function CategoryReadiness({ runtime }: { runtime: WorkflowStudioRuntime }) {
  const { t } = useI18n();
  const categories = Object.entries(runtime.workflow_categories ?? {});
  return (
    <section className="table-card" data-workflow-studio-section="categories">
      <h2><LocalizedText id="copy.capability_categories_738e35cb" /></h2>
      <div className="metrics-grid">
        {categories.map(([category, value]) => {
          const item = asRecord(value);
          return (
            <MetricCard
              key={category}
              label={localizedProductLabel(category, t)}
              value={`${asText(item.ready_workflows, '0')}/${asText(item.workflow_count, '0')}`}
            />
          );
        })}
      </div>
    </section>
  );
}

function RuntimeState({ runtime }: { runtime: WorkflowStudioRuntime }) {
  const { t } = useI18n();
  const state = runtime.workflow_runtime_state ?? {};
  const documents = asRecord(state.document_lifecycle_operations);
  const processing = asRecord(state.processing_workers);
  const knowledge = asRecord(state.knowledge_operations);
  const assistant = asRecord(state.assistant_operations);
  return (
    <section className="table-card" data-workflow-studio-section="runtime-state">
      <h2><LocalizedText id="copy.runtime_evidence_d74f6e81" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.document_versions_228bd2a2')} value={documents.total_document_versions} />
        <MetricCard label={t('copy.storage_verified_ad7b0cbb')} value={documents.storage_verified} />
        <MetricCard label={t('copy.processing_completed_52eeddf5')} value={processing.processing_completed} />
        <MetricCard label={t('copy.knowledge_indexed_47665217')} value={knowledge.indexed_chunks} />
        <MetricCard label={t('copy.assistant_executions_4ad21503')} value={assistant.assistant_runtime_executions} />
        <MetricCard label={t('copy.capability_definitions_3a5d00ad')} value={state.workflow_definition_count} />
      </div>
    </section>
  );
}

function Diagnostics({ runtime }: { runtime: WorkflowStudioRuntime }) {
  const { t } = useI18n();
  const diagnostics = runtime.workflow_diagnostics ?? {};
  const dependencies = runtime.workflow_dependencies ?? {};
  const groups = [
    [t('copy.missing_prerequisites_822f4703'), asList(dependencies.missing_prerequisites)],
    [t('copy.warnings_1430f976'), runtime.warnings],
    [t('copy.pending_capabilities_84fd1f5a'), runtime.pending_capabilities],
    [t('copy.recommendations_4faa65b5'), runtime.workflow_recommendations],
  ];
  return (
    <section className="table-card" data-workflow-studio-section="diagnostics">
      <h2><LocalizedText id="copy.capability_diagnostics_00fca9be" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.dependency_edges_3f6d73d1')} value={dependencies.dependency_count} />
        <MetricCard label={t('copy.missing_prerequisites_822f4703')} value={dependencies.missing_prerequisite_count} />
        <MetricCard label={t('copy.idempotency_support_48e4d0a9')} value={asRecord(diagnostics.idempotency_support).supported} />
        <MetricCard label={t('copy.retry_capability_b018ad0e')} value={asRecord(diagnostics.retry_capability).supported} />
        <MetricCard label={t('copy.resume_capability_94a97112')} value={asRecord(diagnostics.resume_capability).supported} />
        <MetricCard label={t('copy.reference_capability_1caeb7ef')} value={asRecord(runtime.reference_tenant).reference_tenant_workflow_readiness} />
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

export function WorkflowStudioWorkspace() {
  const { t } = useI18n();
  const [runtime, setRuntime] = useState<WorkflowStudioRuntime | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const payload = await getWorkflowStudioRuntime();
        if (!cancelled) setRuntime(payload);
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : t('feedback.capabilityInventoryUnavailable'));
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

  if (loading && !runtime) {
    return (
      <section className="card" data-workflow-studio-section="loading">
        <h2><LocalizedText id="copy.loading_capability_inventory_ad0bacb9" /></h2>
        <p><LocalizedText id="copy.retrieving_platform_capability_status_d6c5e001" /></p>
      </section>
    );
  }

  if (error || !runtime) {
    return (
      <section className="card" data-workflow-studio-section="error">
        <h2><LocalizedText id="copy.capability_inventory_unavailable_27453e77" /></h2>
        <p>{error ?? <LocalizedText id="copy.no_capability_inventory_was_returned_4576fd34" />}</p>
        <button className="button secondary" type="button" onClick={() => setReloadToken((value) => value + 1)}><LocalizedText id="common.actions.retry" /></button>
      </section>
    );
  }

  return (
    <div className="product-workspace">
      {loading ? <p className="context-message"><LocalizedText id="copy.refreshing_capability_status_20ec1601" /></p> : null}
      <section className="card inline-state"><div><h2><LocalizedText id="copy.capability_inventory_9b35444e" /></h2><p><LocalizedText id="copy.review_what_the_platform_supports_and_whether_each_c_23f6c98c" /></p></div></section>
      <WorkflowInventory runtime={runtime} />
      <details className="advanced-panel"><summary><LocalizedText id="copy.internal_capability_codes_and_advanced_diagnostics_224d341f" /></summary><div className="advanced-panel-content"><Summary runtime={runtime} /><CategoryReadiness runtime={runtime} /><RuntimeState runtime={runtime} /><Diagnostics runtime={runtime} /><section className="table-card"><h2><LocalizedText id="copy.internal_capability_codes_07d644da" /></h2><table><thead><tr><th><LocalizedText id="common.name" /></th><th><LocalizedText id="copy.internal_code_99a01f5d" /></th><th><LocalizedText id="copy.evidence_source_c1b6edc7" /></th></tr></thead><tbody>{runtime.workflow_inventory.map((capability) => <tr key={asText(capability.workflow_key)}><td>{asText(capability.workflow_name)}</td><td><small>{asText(capability.workflow_key)}</small></td><td><small>{asText(asRecord(capability.runtime_evidence).source)}</small></td></tr>)}</tbody></table></section></div></details>
    </div>
  );
}
