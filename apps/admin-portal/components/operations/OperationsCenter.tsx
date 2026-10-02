'use client';

import { useI18n } from '../../i18n/I18nProvider';

import { LocalizedDate, LocalizedText } from '../layout/LocalizedText';

import { useEffect, useMemo, useState } from 'react';

import {
  getOperationsCenterRuntime,
  type OperationsCenterRuntime,
} from '../../lib/operations-center-api';
import {
  getGovernanceCenterRuntime,
  type GovernanceCenterRuntime,
} from '../../lib/governance-center-api';
import type { OperationsEvidenceContext } from '../../lib/operations-evidence-context';
import { localizedProductLabel } from '../../lib/presentation';

function asText(value: unknown, fallback = '-'): string {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'boolean') return value ? 'true' : 'false';
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

function MetricCard({ label, value, description }: { label: string; value: unknown; description?: string }) {
  const { t } = useI18n();
  return (
    <article className="metric-card" title={description}>
      <small>{label}</small>
      <strong>{localizedProductLabel(value, t, '0')}</strong>
    </article>
  );
}

function SummaryCards({ runtime }: { runtime: OperationsCenterRuntime }) {
  const { t } = useI18n();
  const summary = runtime.workspace_summary ?? {};
  const rows = [
    ['Operations', summary.operations_ready, summary.operations_ready],
    ['Runtime persistence', summary.runtime_persistence_ready, summary.runtime_persistence_ready],
    ['Document lifecycle', summary.document_lifecycle_ready, summary.document_lifecycle_ready],
    ['Processing', summary.processing_ready, summary.processing_ready],
    ['Knowledge', summary.knowledge_ready, summary.knowledge_ready],
    ['Search', summary.search_ready, summary.search_ready],
    ['Assistants', summary.assistant_ready, summary.assistant_ready],
    ['Connectors', summary.connectors_ready, summary.connectors_ready],
    ['Audit', summary.audit_ready, summary.audit_ready],
  ];
  return (
    <section className="grid" data-operations-center-section="summary-cards">
      {rows.map(([label, value, ready]) => (
        <article className="card health-card" key={label as string}>
          <div className="context-card-header">
            <h2>{label as string}</h2>
            <span className={statusClass(Boolean(ready))}></span>
          </div>
          <span className="metric-value">{localizedProductLabel(value, t)}</span>
        </article>
      ))}
    </section>
  );
}

function RuntimePersistenceSection({ data }: { data: Record<string, unknown> }) {
  const { t } = useI18n();
  return (
    <section className="table-card" data-operations-center-section="runtime-persistence">
      <h2><LocalizedText id="copy.runtime_persistence_dfa8a9e6" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.runtime_records_2c4f6f8d')} value={data.total_runtime_records} />
        <MetricCard label={t('copy.domains_a0d641b3')} value={Object.keys(asRecord(data.runtime_records_by_domain)).length} />
        <MetricCard label={t('copy.statuses_e92aab82')} value={Object.keys(asRecord(data.runtime_records_by_status)).length} />
      </div>
      <table>
        <thead>
          <tr><th><LocalizedText id="copy.domain_9b10914d" /></th><th><LocalizedText id="copy.action_97c89a4d" /></th><th><LocalizedText id="common.status" /></th><th><LocalizedText id="common.created" /></th></tr>
        </thead>
        <tbody>
          {asList(data.recent_runtime_records).map((record) => (
            <tr key={asText(record.runtime_record_id)}>
              <td>{localizedProductLabel(record.runtime_domain, t)}</td>
              <td>{localizedProductLabel(record.runtime_action, t)}</td>
              <td>{localizedProductLabel(record.runtime_status, t)}</td>
              <td><LocalizedDate value={typeof record.created_at === 'string' ? record.created_at : null} /></td>
            </tr>
          ))}
          {asList(data.recent_runtime_records).length === 0 ? <tr><td className="table-empty" colSpan={4}><LocalizedText id="common.noItems" /></td></tr> : null}
        </tbody>
      </table>
    </section>
  );
}

function ContextualEvidenceSection({
  context,
  error,
  loading,
  runtime,
}: {
  context: OperationsEvidenceContext;
  error: string | null;
  loading: boolean;
  runtime: GovernanceCenterRuntime | null;
}) {
  const { t } = useI18n();
  const authoritativeOrganizationId = String(runtime?.workspace_summary?.organization_id ?? '');
  const evidence = runtime && authoritativeOrganizationId === context.organizationId
    ? asRecord(runtime.runtime_evidence)
    : {};
  const allRecords = asList(evidence.recent_runtime_records);
  const relatedRecords = context.domain === 'runtime_evidence'
    ? allRecords
    : allRecords.filter((record) => String(record.runtime_domain ?? '') === context.domain);

  return (
    <section
      className="table-card operations-related-evidence is-selected"
      data-evidence-control={context.controlId}
      data-operations-center-section="contextual-evidence"
    >
      <div className="context-card-header">
        <h2>{t('governanceUx.reviewEvidence')}</h2>
        <span>{relatedRecords.length}</span>
      </div>
      <p><strong>{context.controlId}</strong> · {localizedProductLabel(context.status, t)}</p>
      {loading ? <p role="status"><LocalizedText id="common.loading" /></p> : null}
      {error ? <p role="alert">{error}</p> : null}
      {!loading && !error && relatedRecords.length === 0 ? (
        <div className="empty-state compact">
          <strong>{localizedProductLabel(context.domain, t)}</strong>
          <p><LocalizedText id="common.noItems" /></p>
        </div>
      ) : null}
      {relatedRecords.length > 0 ? (
        <table>
          <thead>
            <tr><th><LocalizedText id="copy.domain_9b10914d" /></th><th><LocalizedText id="common.type" /></th><th><LocalizedText id="common.status" /></th><th><LocalizedText id="common.created" /></th></tr>
          </thead>
          <tbody>
            {relatedRecords.map((record) => (
              <tr data-evidence-related="true" key={asText(record.runtime_record_id)}>
                <td>{localizedProductLabel(record.runtime_domain, t)}</td>
                <td>{localizedProductLabel(record.record_type, t)}</td>
                <td>{localizedProductLabel(record.persistence_status, t)}</td>
                <td><LocalizedDate value={typeof record.occurred_at === 'string' ? record.occurred_at : null} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  );
}

function DocumentLifecycleSection({ data }: { data: Record<string, unknown> }) {
  const { t } = useI18n();
  return (
    <section className="table-card" data-operations-center-section="document-lifecycle">
      <h2><LocalizedText id="copy.document_lifecycle_operations_ec38465d" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('pages.documents.title')} value={data.registered_documents} />
        <MetricCard label={t('copy.versions_a239107e')} value={data.total_document_versions} />
        <MetricCard label={t('copy.artifacts_a5b79f59')} value={data.total_artifacts} />
        <MetricCard label={t('copy.storage_verified_ad7b0cbb')} value={data.storage_verified} />
        <MetricCard label={t('copy.chunks_4a527377')} value={data.chunks_created} />
        <MetricCard label={t('copy.knowledge_indexed_47665217')} value={data.knowledge_indexed} />
        <MetricCard label={t('copy.chat_ready_a5697bb5')} value={data.chat_ready} />
        <MetricCard label={t('copy.failed_lifecycles_5b81d8dd')} value={data.failed_lifecycles} />
      </div>
      <table>
        <thead>
          <tr><th><LocalizedText id="copy.lifecycle_033df3d2" /></th><th><LocalizedText id="copy.storage_9e092dda" /></th><th><LocalizedText id="copy.processing_e63451d3" /></th><th><LocalizedText id="pages.knowledge.title" /></th><th><LocalizedText id="pages.search.title" /></th><th><LocalizedText id="copy.chat_2ced57f1" /></th></tr>
        </thead>
        <tbody>
          {asList(data.recent_lifecycles).map((item) => (
            <tr key={asText(item.document_version_id)}>
              <td>{localizedProductLabel(item.lifecycle_status, t)}</td>
              <td>{localizedProductLabel(item.storage_status, t)}</td>
              <td>{localizedProductLabel(item.processing_status, t)}</td>
              <td>{localizedProductLabel(item.knowledge_index_status, t)}</td>
              <td>{localizedProductLabel(item.enterprise_search_status, t)}</td>
              <td>{localizedProductLabel(item.chat_status, t)}</td>
            </tr>
          ))}
          {asList(data.recent_lifecycles).length === 0 ? <tr><td className="table-empty" colSpan={6}><LocalizedText id="common.noItems" /></td></tr> : null}
        </tbody>
      </table>
    </section>
  );
}

function ProcessingSection({ data }: { data: Record<string, unknown> }) {
  const { t } = useI18n();
  return (
    <section className="table-card" data-operations-center-section="processing-workers">
      <h2><LocalizedText id="copy.processing_and_workers_4b82ad1a" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.processing_executions_12341b1e')} value={data.processing_executions} />
        <MetricCard label={t('status.completed')} value={data.processing_completed} />
        <MetricCard label={t('copy.failed_09fef5d8')} value={data.processing_failed} />
        <MetricCard label={t('copy.pending_96f608c1')} value={data.processing_pending} />
        <MetricCard label={t('copy.worker_ready_2bae8870')} value={data.worker_runtime_ready} />
        <MetricCard label={t('copy.worker_pending_db8bc309')} value={data.worker_execution_pending} />
        <MetricCard label={t('copy.worker_failures_4ea2fad2')} value={data.worker_failures} />
        <MetricCard label={t('copy.retry_candidates_4ac084c0')} value={data.retry_candidates} />
      </div>
    </section>
  );
}

function KnowledgeSearchSection({
  knowledge,
  search,
}: {
  knowledge: Record<string, unknown>;
  search: Record<string, unknown>;
}) {
  const { t } = useI18n();
  return (
    <section className="table-card" data-operations-center-section="knowledge-search">
      <h2><LocalizedText id="copy.knowledge_and_search_operations_bee59c33" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.knowledge_documents_e25dbfc5')} value={knowledge.knowledge_documents} />
        <MetricCard label={t('copy.knowledge_chunks_99e06082')} value={knowledge.knowledge_chunks} />
        <MetricCard label={t('copy.indexed_documents_21aeb5c3')} value={knowledge.indexed_documents} />
        <MetricCard label={t('copy.indexed_chunks_86bc1069')} value={knowledge.indexed_chunks} />
        <MetricCard label={t('copy.publication_failed_58f1ed5a')} value={knowledge.publication_failed} />
        <MetricCard label={t('copy.search_requests_f13d828f')} value={search.search_requests} />
        <MetricCard label={t('copy.successful_searches_63c6f0ed')} value={search.successful_searches} />
        <MetricCard
          label={t('copy.search_coverage_dd9880f8')}
          value={search.search_result_coverage ?? t('copy.not_measurable_b14fa542')}
          description={t('copy.indexed_governed_knowledge_chunks_divided_by_searcha_7938dbb8')}
        />
      </div>
    </section>
  );
}

function AssistantConnectorSection({
  assistant,
  connectors,
}: {
  assistant: Record<string, unknown>;
  connectors: Record<string, unknown>;
}) {
  const { t } = useI18n();
  return (
    <section className="table-card" data-operations-center-section="assistant-connectors">
      <h2><LocalizedText id="copy.assistant_and_connector_operations_2e56f605" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.assistant_sessions_b021b0d0')} value={assistant.assistant_sessions} />
        <MetricCard label={t('copy.assistant_executions_4ad21503')} value={assistant.assistant_runtime_executions} />
        <MetricCard label={t('copy.conversations_07c59b44')} value={assistant.conversation_count} />
        <MetricCard label={t('copy.turns_3037e104')} value={assistant.turn_count} />
        <MetricCard label={t('copy.llm_executions_82016503')} value={assistant.llm_execution_records} />
        <MetricCard label={t('copy.connector_count_77521525')} value={connectors.connector_count} />
        <MetricCard label={t('copy.connector_runs_5f98b96f')} value={connectors.connector_runs} />
        <MetricCard label={t('copy.failed_connector_runs_be893146')} value={connectors.failed_connector_runs} />
      </div>
    </section>
  );
}

function FeedbackAuditSection({ data }: { data: Record<string, unknown> }) {
  const { t } = useI18n();
  return (
    <section className="table-card" data-operations-center-section="feedback-audit">
      <h2><LocalizedText id="copy.feedback_and_audit_operations_df1cf66a" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.feedback_c8d7677e')} value={data.feedback_count} />
        <MetricCard label={t('copy.pending_feedback_36065f38')} value={data.feedback_pending} />
        <MetricCard label={t('copy.audit_events_9e7d8c07')} value={data.audit_event_count} />
        <MetricCard label={t('copy.traceability_ready_4881d8fe')} value={data.traceability_ready} />
      </div>
    </section>
  );
}

function OperationalObservabilitySection({ runtime }: { runtime: OperationsCenterRuntime }) {
  const { t } = useI18n();
  const readiness = asRecord(runtime.operational_readiness);
  const components = asRecord(runtime.component_summary);
  const workers = asRecord(runtime.worker_summary);
  const scheduler = asRecord(runtime.scheduler_summary);
  const leases = asRecord(runtime.lease_summary);
  const executions = asRecord(runtime.execution_summary);
  const retries = asRecord(runtime.retry_summary);
  const incidents = asRecord(runtime.incident_summary);
  return (
    <section className="table-card" data-operations-center-section="operational-observability">
      <h2><LocalizedText id="copy.operational_observability_and_recovery_b93036d5" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.operational_readiness_f83f3042')} value={readiness.status} />
        <MetricCard label={t('copy.components_9289473e')} value={components.component_count} />
        <MetricCard label={t('copy.workers_b6ef3acd')} value={workers.worker_count} />
        <MetricCard label={t('copy.scheduler_heartbeat_f44f5790')} value={scheduler.heartbeat_fresh} />
        <MetricCard label={t('copy.active_leases_8d84fb02')} value={leases.active_leases} />
        <MetricCard label={t('copy.expired_leases_d1daba1d')} value={leases.expired_leases} />
        <MetricCard label={t('copy.executions_8999e584')} value={executions.execution_count} />
        <MetricCard label={t('copy.retries_13093e56')} value={retries.retry_count} />
        <MetricCard label={t('copy.open_incidents_77d7229d')} value={incidents.open_incidents} />
      </div>
      <div className="alerts-grid">
        <article className="context-card">
          <strong><LocalizedText id="copy.operational_gates_6b458477" /></strong>
          <ul className="compact-list">
            {asList(readiness.gates).map((gate) => (
              <li key={asText(gate.gate_code)}>
                {asText(gate.gate_code)}: {asText(gate.status)}
              </li>
            ))}
          </ul>
        </article>
        <article className="context-card">
          <strong><LocalizedText id="copy.next_actions_7b09055a" /></strong>
          <ul className="compact-list">
            {(runtime.next_actions ?? []).map((action, index) => (
              <li key={`operation-action-${index}`}>{asText(action.code ?? action.source_gate)}</li>
            ))}
          </ul>
        </article>
      </div>
    </section>
  );
}

function SecurityPostureSection({ runtime }: { runtime: OperationsCenterRuntime }) {
  const { t } = useI18n();
  const security = asRecord(runtime.security_readiness);
  const gates = asList(security.gates);
  const findings = asList(security.findings);
  return (
    <section className="table-card" data-operations-center-section="security-posture">
      <h2><LocalizedText id="copy.security_posture_9f0671ed" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.security_readiness_487b9974')} value={security.status} />
        <MetricCard label={t('copy.security_ready_96fddb06')} value={security.security_ready} />
        <MetricCard label={t('copy.security_gates_1d04951b')} value={gates.length} />
        <MetricCard label={t('copy.findings_ca9b7e7e')} value={findings.length} />
      </div>
      <ul className="compact-list">
        {gates.map((gate) => (
          <li key={asText(gate.gate_code)}>
            {asText(gate.gate_code).replaceAll('_', ' ')}: {asText(gate.status)}
          </li>
        ))}
      </ul>
    </section>
  );
}

function DiagnosticsSection({ diagnostics }: { diagnostics: OperationsCenterRuntime['diagnostics'] }) {
  const { t } = useI18n();
  const groups = [
    ['Blocking issues', diagnostics.blocking_issues ?? []],
    ['Warnings', diagnostics.warnings ?? []],
    ['Pending capabilities', diagnostics.pending_capabilities ?? []],
    ['Degraded items', diagnostics.degraded_items ?? []],
    ['Failed items', diagnostics.failed_items ?? []],
    ['Retry candidates', diagnostics.retry_candidates ?? []],
    ['Recommendations', diagnostics.operational_recommendations ?? []],
  ];
  return (
    <section className="table-card" data-operations-center-section="diagnostics">
      <h2><LocalizedText id="copy.failures_retries_and_diagnostics_0ffa5444" /></h2>
      <div className="alerts-grid">
        {groups.map(([title, values]) => (
          <article className="context-card" key={title as string}>
            <div className="context-card-header">
              <strong>{title as string}</strong>
              <span>{(values as Record<string, unknown>[]).length}</span>
            </div>
            {(values as Record<string, unknown>[]).length > 0 ? (
              <ul className="compact-list">
                {(values as Record<string, unknown>[]).map((item, index) => (
                  <li key={`${title}-${index}`}>{issueText(item, t)}</li>
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

export function OperationsCenter({
  evidenceContext = null,
}: {
  evidenceContext?: OperationsEvidenceContext | null;
}) {
  const { t } = useI18n();
  const [runtime, setRuntime] = useState<OperationsCenterRuntime | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [evidenceRuntime, setEvidenceRuntime] = useState<GovernanceCenterRuntime | null>(null);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const payload = await getOperationsCenterRuntime();
        if (!cancelled) setRuntime(payload);
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : t('feedback.operationsRuntimeUnavailable'));
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

  useEffect(() => {
    let cancelled = false;
    if (!evidenceContext) {
      setEvidenceRuntime(null);
      setEvidenceLoading(false);
      setEvidenceError(null);
      return () => { cancelled = true; };
    }
    setEvidenceRuntime(null);
    setEvidenceLoading(true);
    setEvidenceError(null);
    void getGovernanceCenterRuntime()
      .then((payload) => {
        if (!cancelled) setEvidenceRuntime(payload);
      })
      .catch((loadError) => {
        if (!cancelled) {
          setEvidenceError(loadError instanceof Error ? loadError.message : t('feedback.governanceRuntimeUnavailable'));
        }
      })
      .finally(() => {
        if (!cancelled) setEvidenceLoading(false);
      });
    return () => { cancelled = true; };
  }, [evidenceContext, t]);

  const summary = runtime?.workspace_summary ?? {};
  const diagnostics = useMemo(() => runtime?.diagnostics ?? {}, [runtime]);

  if (loading) {
    return (
      <section className="card" data-operations-center-section="loading">
        <h2><LocalizedText id="copy.loading_operations_center_e00b1176" /></h2>
        <p><LocalizedText id="copy.retrieving_operational_state_from_postgresql_backed__41d22687" /></p>
      </section>
    );
  }

  if (error || !runtime) {
    return (
      <section className="card" data-operations-center-section="error">
        <h2><LocalizedText id="copy.operations_center_unavailable_75399550" /></h2>
        <p>{error ?? <LocalizedText id="copy.no_operations_center_runtime_payload_was_returned_47aca44c" />}</p>
        <button className="button secondary" type="button" onClick={() => setReloadToken((value) => value + 1)}><LocalizedText id="common.actions.retry" /></button>
      </section>
    );
  }

  return (
    <div className="platform-home" data-operations-center="ready">
      <header className="platform-hero" data-operations-center-section="summary">
        <div>
          <span className="badge"><LocalizedText id="copy.operations_center_b1cb39bc" /></span>
          <h2><LocalizedText id="copy.operations_overview_d6b6ca08" /></h2>
          <p><LocalizedText id="copy.runtime_state_lifecycle_activity_workers_failures_re_3dcab55c" /></p>
        </div>
        <div className="platform-status-panel">
          <p><span className={statusClass(runtime.runtime_status === 'ready')}></span> <LocalizedText id="copy.runtime_c4740e4c" />{localizedProductLabel(runtime.runtime_status, t)}</p>
          <p><LocalizedText id="copy.operations_a5463395" />{localizedProductLabel(summary.operations_ready, t)}</p>
          <p><LocalizedText id="copy.persistence_6594cefb" />{localizedProductLabel(summary.runtime_persistence_ready, t)}</p>
          <p><LocalizedText id="copy.postgresql_source_602da08d" />{localizedProductLabel(runtime.postgresql_source_of_truth, t)}</p>
          <p><LocalizedText id="copy.side_effects_8b6f4c47" />{localizedProductLabel(runtime.side_effects_performed, t)}</p>
        </div>
      </header>

      {evidenceContext ? (
        <ContextualEvidenceSection
          context={evidenceContext}
          error={evidenceError}
          loading={evidenceLoading || (!evidenceRuntime && !evidenceError)}
          runtime={evidenceRuntime}
        />
      ) : null}
      <SummaryCards runtime={runtime} />
      <RuntimePersistenceSection data={runtime.runtime_persistence} />
      <DocumentLifecycleSection data={runtime.document_lifecycle_operations} />
      <ProcessingSection data={runtime.processing_workers} />
      <KnowledgeSearchSection
        knowledge={runtime.knowledge_operations}
        search={runtime.enterprise_search_operations}
      />
      <AssistantConnectorSection
        assistant={runtime.assistant_operations}
        connectors={runtime.connector_operations}
      />
      <FeedbackAuditSection data={runtime.feedback_audit_operations} />
      <OperationalObservabilitySection runtime={runtime} />
      <SecurityPostureSection runtime={runtime} />
      <DiagnosticsSection diagnostics={diagnostics} />
    </div>
  );
}
