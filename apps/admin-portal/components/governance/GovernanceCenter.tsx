'use client';

import { LocalizedDate, LocalizedText } from '../layout/LocalizedText';

import { useI18n } from '../../i18n/I18nProvider';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  getGovernanceCenterRuntime,
  type GovernanceCenterRuntime,
} from '../../lib/governance-center-api';
import { governanceScopeLabel, governanceStatusLabel, normalizeGovernanceDiagnostics } from '../../lib/governance-presentation';
import { buildOperationsEvidenceHref } from '../../lib/operations-evidence-context';
import { platformCapabilityAvailable } from '../../lib/platform-dashboard-api';
import { localizedProductLabel, productLabel } from '../../lib/presentation';
import { useOrganization } from '../organization/OrganizationContext';

type PlatformOperationsAccessState = 'available' | 'checking' | 'restricted';

function asText(value: unknown, fallback = '-'): string {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'boolean') return value ? 'Ready' : 'Not ready';
  if (typeof value === 'string') return productLabel(value, fallback);
  return String(value);
}

function readableActor(item: Record<string, unknown>, fallback: string): string {
  const value = String(item.actor_name ?? item.actor_type ?? item.actor_id ?? '');
  return /^[0-9a-f]{8}-[0-9a-f-]{27,}$/i.test(value) ? fallback : value || fallback;
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

function asLocalizedDateValue(value: unknown): string | number | Date | null | undefined {
  if (value === null || value === undefined) return value;
  if (typeof value === 'string' || typeof value === 'number' || value instanceof Date) return value;
  return undefined;
}

function statusClass(ready: boolean): string {
  return ready ? 'status-dot ready' : 'status-dot degraded';
}

const GOVERNANCE_ITEM_KEYS: Record<string, string> = {
  audit: 'governanceUx.items.audit',
  assistant_traceability: 'governanceUx.items.assistantTraceability',
  classification: 'governanceUx.items.classification',
  classification_rules_missing: 'governanceUx.items.classificationRulesMissing',
  configure_classification_rules: 'governanceUx.items.configureClassificationRules',
  configure_retention_policies: 'governanceUx.items.configureRetentionPolicies',
  document_lineage: 'governanceUx.items.documentLineage',
  feedback: 'governanceUx.items.feedback',
  knowledge_lineage: 'governanceUx.items.knowledgeLineage',
  policy: 'governanceUx.items.policy',
  retention: 'governanceUx.items.retention',
  retention_policies_missing: 'governanceUx.items.retentionPoliciesMissing',
  review_audit_capture: 'governanceUx.items.reviewAuditCapture',
  review_runtime_evidence: 'governanceUx.items.reviewRuntimeEvidence',
  runtime_evidence: 'governanceUx.items.runtimeEvidence',
  security_governance_incomplete: 'governanceUx.items.securityGovernanceIncomplete',
};

function governanceItemText(item: Record<string, unknown>, translate: (key: string) => string): string {
  const identifier = String(item.code ?? item.item_id ?? item.domain ?? '').trim().toLowerCase();
  return GOVERNANCE_ITEM_KEYS[identifier]
    ? translate(GOVERNANCE_ITEM_KEYS[identifier])
    : translate('governanceUx.items.unknown');
}

function governanceDomain(item: Record<string, unknown>): string {
  const explicitDomain = String(item.domain ?? item.item_id ?? '').trim();
  if (explicitDomain) return explicitDomain;
  const code = String(item.code ?? '').trim();
  return code.startsWith('review_') ? code.slice('review_'.length) : code;
}

function governanceDestination(
  item: Record<string, unknown>,
  organizationId: string | null,
  fallbackStatus: string,
): { href: string; requiresPlatformOperations: boolean } | null {
  const code = String(item.code ?? item.item_id ?? item.domain ?? '');
  if ((code === 'review_runtime_evidence' || code === 'runtime_evidence') && organizationId) {
    return {
      href: buildOperationsEvidenceHref({
        organizationId,
        controlId: code,
        domain: governanceDomain(item),
        status: String(item.status ?? fallbackStatus),
      }),
      requiresPlatformOperations: true,
    };
  }
  if (code === 'policy') return { href: '/security', requiresPlatformOperations: false };
  if (code === 'document_lineage') return { href: '/documents', requiresPlatformOperations: false };
  if (code === 'knowledge_lineage') return { href: '/knowledge', requiresPlatformOperations: false };
  return null;
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

function SummaryCards({ runtime }: { runtime: GovernanceCenterRuntime }) {
  const { t } = useI18n();
  const summary = runtime.workspace_summary ?? {};
  const rows = [
    ['governanceUx.summary.governance', summary.governance_ready, summary.governance_ready],
    ['governanceUx.summary.audit', summary.audit_ready, summary.audit_ready],
    ['governanceUx.summary.feedback', summary.feedback_ready, summary.feedback_ready],
    ['governanceUx.summary.classification', summary.classification_ready, summary.classification_ready],
    ['governanceUx.summary.retention', summary.retention_ready, summary.retention_ready],
    ['governanceUx.summary.policy', summary.policy_ready, summary.policy_ready],
    ['governanceUx.summary.lineage', summary.lineage_ready, summary.lineage_ready],
    ['governanceUx.summary.evidence', summary.evidence_ready, summary.evidence_ready],
    ['governanceUx.summary.compliance', summary.compliance_ready, summary.compliance_ready],
  ];
  return (
    <section className="grid" data-governance-center-section="summary-cards">
      {rows.map(([label, value, ready]) => (
        <article className="card health-card" key={label as string}>
          <div className="context-card-header">
            <h2>{t(label as string)}</h2>
            <span className={statusClass(Boolean(ready))}></span>
          </div>
          <span className="metric-value">{localizedProductLabel(value, t)}</span>
        </article>
      ))}
    </section>
  );
}

function AuditSection({ data }: { data: Record<string, unknown> }) {
  const { t } = useI18n();
  return (
    <section className="table-card" data-governance-center-section="audit-governance">
      <h2><LocalizedText id="copy.audit_governance_23de6eb5" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.audit_events_9e7d8c07')} value={data.audit_event_count} />
        <MetricCard label={t('copy.audit_actions_6d7df76f')} value={data.audit_actions_count} />
        <MetricCard label={t('copy.audit_history_5714d2e0')} value={data.audit_history_count} />
        <MetricCard label={t('copy.resource_types_d1143f96')} value={Object.keys(asRecord(data.audit_events_by_resource_type)).length} />
      </div>
      <table>
        <thead>
          <tr><th><LocalizedText id="copy.resource_021493f3" /></th><th><LocalizedText id="copy.summary_12b71c3e" /></th><th><LocalizedText id="copy.actor_cbd19b5c" /></th><th><LocalizedText id="common.created" /></th></tr>
        </thead>
        <tbody>
          {asList(data.recent_audit_events).map((event) => (
            <tr key={asText(event.audit_event_id)}>
              <td>{localizedProductLabel(event.resource_type, t)}</td>
              <td>{asText(event.summary)}</td>
              <td>{readableActor(event, t('copy.system_317f1e76'))}</td>
              <td>{<LocalizedDate value={asLocalizedDateValue(event.created_at)} />}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function FeedbackSection({ data }: { data: Record<string, unknown> }) {
  const { t } = useI18n();
  return (
    <section className="table-card" data-governance-center-section="feedback-governance">
      <h2><LocalizedText id="copy.feedback_governance_295103b5" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.feedback_c8d7677e')} value={data.feedback_count} />
        <MetricCard label={t('copy.pending_96f608c1')} value={data.feedback_pending} />
        <MetricCard label={t('copy.reviewed_31ef8593')} value={data.feedback_reviewed} />
        <MetricCard label={t('copy.ratings_14021e13')} value={Object.keys(asRecord(data.feedback_by_rating)).length} />
      </div>
    </section>
  );
}

function ClassificationRetentionSection({
  classification,
  retention,
}: {
  classification: Record<string, unknown>;
  retention: Record<string, unknown>;
}) {
  const { t } = useI18n();
  return (
    <section className="table-card" data-governance-center-section="classification-retention">
      <h2><LocalizedText id="copy.classification_and_retention_1838995f" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.classification_rules_46a532c5')} value={classification.classification_rules_count} />
        <MetricCard label={t('copy.unclassified_documents_9ff3a66c')} value={classification.unclassified_documents} />
        <MetricCard label={t('copy.classification_ready_adfd496d')} value={asRecord(classification.classification_readiness).status} />
        <MetricCard label={t('copy.retention_policies_62b9cc1e')} value={retention.retention_policies_count} />
        <MetricCard label={t('copy.documents_with_retention_d2bad5a9')} value={retention.documents_with_retention_policy} />
        <MetricCard label={t('copy.missing_retention_9bf50d4c')} value={retention.documents_missing_retention_policy} />
      </div>
    </section>
  );
}

function PolicyEvidenceSection({
  policy,
  evidence,
}: {
  policy: Record<string, unknown>;
  evidence: Record<string, unknown>;
}) {
  const { t } = useI18n();
  return (
    <section className="table-card" data-governance-center-section="policy-evidence">
      <h2><LocalizedText id="copy.policy_governance_and_runtime_evidence_7df2267d" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.roles_47dcc27d')} value={policy.roles_count} />
        <MetricCard label={t('copy.permissions_d06d5557')} value={policy.permissions_count} />
        <MetricCard label={t('copy.policies_8d611849')} value={policy.policies_count} />
        <MetricCard label={t('copy.role_assignments_c91edf78')} value={policy.role_assignments_count} />
        <MetricCard label={t('copy.runtime_records_2c4f6f8d')} value={evidence.runtime_records_count} />
        <MetricCard label={t('copy.evidence_coverage_f96a6c2c')} value={evidence.evidence_coverage} />
      </div>
    </section>
  );
}

function LineageSection({
  documentLineage,
  knowledgeLineage,
}: {
  documentLineage: Record<string, unknown>;
  knowledgeLineage: Record<string, unknown>;
}) {
  const { t } = useI18n();
  return (
    <section className="table-card" data-governance-center-section="lineage">
      <h2><LocalizedText id="copy.document_and_knowledge_lineage_307f9776" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.document_records_16696a76')} value={documentLineage.document_records_count} />
        <MetricCard label={t('copy.document_versions_228bd2a2')} value={documentLineage.document_versions_count} />
        <MetricCard label={t('copy.artifacts_a5b79f59')} value={documentLineage.artifacts_count} />
        <MetricCard label={t('copy.chunks_4a527377')} value={documentLineage.chunks_count} />
        <MetricCard label={t('copy.knowledge_documents_e25dbfc5')} value={knowledgeLineage.knowledge_documents_count} />
        <MetricCard label={t('copy.knowledge_chunks_99e06082')} value={knowledgeLineage.knowledge_chunks_count} />
        <MetricCard label={t('copy.search_ready_028329ac')} value={knowledgeLineage.knowledge_to_search_ready} />
      </div>
      <table>
        <thead>
          <tr><th><LocalizedText id="copy.chunks_4a527377" /></th><th><LocalizedText id="pages.knowledge.title" /></th><th><LocalizedText id="pages.search.title" /></th><th><LocalizedText id="copy.traceability_61d2e70b" /></th></tr>
        </thead>
        <tbody>
          {asList(documentLineage.recent_document_lineage).map((item) => (
            <tr key={asText(item.document_version_id)}>
              <td>{asText(item.chunk_count, '0')}</td>
              <td>{item.knowledge_document_id ? <LocalizedText id="status.published" /> : <LocalizedText id="status.notEvaluated" />}</td>
              <td>{localizedProductLabel(item.enterprise_search_ready, t)}</td>
              <td>{localizedProductLabel(item.traceability_status, t)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function AssistantComplianceSection({
  assistant,
  compliance,
}: {
  assistant: Record<string, unknown>;
  compliance: Record<string, unknown>;
}) {
  const { t } = useI18n();
  return (
    <section className="table-card" data-governance-center-section="assistant-compliance">
      <h2><LocalizedText id="copy.assistant_traceability_and_compliance_a81d3b03" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('dynamic.assistants')} value={assistant.assistant_count} />
        <MetricCard label={t('copy.conversations_07c59b44')} value={assistant.conversation_count} />
        <MetricCard label={t('copy.turns_3037e104')} value={assistant.conversation_turn_count} />
        <MetricCard label={t('copy.runtime_executions_dd145dc5')} value={assistant.assistant_runtime_execution_count} />
        <MetricCard label={t('copy.citations_fd328df3')} value={assistant.citation_verification_count} />
        <MetricCard label={t('copy.responses_633f6e8b')} value={assistant.assistant_response_count} />
        <MetricCard label={t('copy.governance_score_2b18aea8')} value={compliance.governance_score} />
        <MetricCard label={t('copy.compliance_ready_373baed7')} value={compliance.compliance_ready} />
      </div>
    </section>
  );
}

function DiagnosticsSection({
  diagnostics,
  operationsAccess,
  organizationId,
}: {
  diagnostics: GovernanceCenterRuntime['diagnostics'];
  operationsAccess: PlatformOperationsAccessState;
  organizationId: string | null;
}) {
  const { t } = useI18n();
  const normalized = normalizeGovernanceDiagnostics(diagnostics);
  const groups = [
    ['blocker', 'governanceUx.groups.operationalBlockers', 'governanceUx.groups.operationalBlockersHelp', normalized.operationalBlockers],
    ['degraded', 'governanceUx.groups.nonBlockingDegradation', 'governanceUx.groups.nonBlockingDegradationHelp', normalized.nonBlockingDegradations],
    ['review', 'governanceUx.groups.administrativeReview', 'governanceUx.groups.administrativeReviewHelp', normalized.administrativeReviews],
  ];
  return (
    <section className="table-card" data-governance-center-section="diagnostics">
      <h2><LocalizedText id="copy.governance_diagnostics_91751b35" /></h2>
      <div className="alerts-grid">
        {groups.map(([kind, title, help, values]) => (
          <article className={`context-card governance-diagnostic governance-diagnostic-${kind}`} key={kind as string}>
            <div className="context-card-header">
              <strong>{t(title as string)}</strong>
              <span>{(values as Record<string, unknown>[]).length}</span>
            </div>
            <p>{t(help as string)}</p>
            {(values as Record<string, unknown>[]).length > 0 ? (
              <ul className="compact-list">
                {(values as Record<string, unknown>[]).map((item, index) => {
                  const destination = governanceDestination(item, organizationId, String(kind));
                  const identifier = String(item.code ?? item.item_id ?? item.domain ?? '');
                  return (
                    <li key={`${kind}-${index}`}>
                      <strong>{governanceItemText(item, t)}</strong>
                      {identifier ? <small className="table-secondary">{t('governanceUx.technicalCode')}: <code>{identifier}</code></small> : null}
                      {item.status ? <>
                        <span> · {governanceStatusLabel(item.status, t)}</span>
                        <small className="table-secondary">{t('governanceUx.technicalStatusCode')}: <code>{String(item.status)}</code></small>
                      </> : null}
                      {destination && (!destination.requiresPlatformOperations || operationsAccess === 'available') ? (
                        <p><a className="text-link" href={destination.href}>{t('governanceUx.reviewEvidence')}</a></p>
                      ) : null}
                      {destination?.requiresPlatformOperations && operationsAccess !== 'available' ? (
                        <p className="table-secondary" data-governance-evidence-access={operationsAccess}>
                          {t(operationsAccess === 'checking' ? 'copy.checking_access_c5108c02' : 'navigation.platformPermissionRequired')}
                        </p>
                      ) : null}
                    </li>
                  );
                })}
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

export function GovernanceCenter() {
  const { t } = useI18n();
  const {
    capabilitiesLoading,
    capabilitiesResolved,
    navigationCapabilities,
    organization,
  } = useOrganization();
  const [runtime, setRuntime] = useState<GovernanceCenterRuntime | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestVersion = useRef(0);

  const load = useCallback(async () => {
      const version = ++requestVersion.current;
      setLoading(true);
      setError(null);
      try {
        const payload = await getGovernanceCenterRuntime();
        if (version === requestVersion.current) setRuntime(payload);
      } catch (loadError) {
        if (version === requestVersion.current) {
          setError(loadError instanceof Error ? loadError.message : t('feedback.governanceRuntimeUnavailable'));
        }
      } finally {
        if (version === requestVersion.current) setLoading(false);
      }
  }, [t]);

  useEffect(() => {
    setRuntime(null);
    void load();
    return () => { requestVersion.current += 1; };
  }, [load, organization?.id]);

  const summary = runtime?.workspace_summary ?? {};
  const diagnostics = useMemo(() => runtime?.diagnostics ?? {}, [runtime]);
  const normalizedDiagnostics = useMemo(
    () => normalizeGovernanceDiagnostics(runtime?.diagnostics),
    [runtime],
  );
  const operationsAccess: PlatformOperationsAccessState = capabilitiesLoading || !capabilitiesResolved
    ? 'checking'
    : platformCapabilityAvailable(navigationCapabilities, 'operations')
      ? 'available'
      : 'restricted';

  if (loading && !runtime) {
    return (
      <section className="card" data-governance-center-section="loading">
        <h2><LocalizedText id="copy.loading_governance_center_e881d1c5" /></h2>
        <p><LocalizedText id="copy.retrieving_governance_state_from_postgresql_backed_p_f74ba186" /></p>
      </section>
    );
  }

  if (!runtime) {
    return (
      <section className="card" data-governance-center-section="error">
        <h2><LocalizedText id="copy.governance_center_unavailable_e0ee0cc5" /></h2>
        <p>{error ?? <LocalizedText id="copy.no_governance_center_runtime_payload_was_returned_3fc0ac15" />}</p>
        <button className="button secondary" type="button" onClick={() => void load()}><LocalizedText id="common.actions.retry" /></button>
      </section>
    );
  }

  const blockingCount = normalizedDiagnostics.operationalBlockers.length;
  const degradationCount = normalizedDiagnostics.nonBlockingDegradations.length;
  const administrativeReviewCount = normalizedDiagnostics.administrativeReviews.length;
  const governanceReady = summary.governance_ready === true;

  return (
    <div className="platform-home" data-governance-center="ready">
      {error ? <p className="context-message context-error" role="alert">{t('dynamic.latestGovernanceEvidenceError')} <button className="button secondary" type="button" onClick={() => void load()}><LocalizedText id="common.actions.retry" /></button></p> : null}
      {loading ? <p className="context-message" role="status"><LocalizedText id="copy.refreshing_governance_evidence_9c753023" /></p> : null}
      <header className="platform-hero" data-governance-center-section="summary">
        <div>
          <span className="badge"><LocalizedText id="copy.governance_center_83c91762" /></span>
          <h2>{governanceReady ? <LocalizedText id="copy.governance_controls_are_ready_111f0b33" /> : <LocalizedText id="copy.governance_needs_attention_d707cd3b" />}</h2>
          <p>{t('dynamic.governanceDecisionScope', { organization: organization?.name ?? t('dynamic.activeOrganization') })}</p>
          {degradationCount > 0 ? <p>{t('dynamic.degradedCapabilityCount', { count: degradationCount, value: degradationCount })}{blockingCount === 0 ? ` ${t('dynamic.degradedNotFormalIssue')}` : ''}</p> : null}
        </div>
        <div className="platform-status-panel">
          <p><span className={statusClass(runtime.runtime_status === 'ready')}></span> {governanceStatusLabel(runtime.runtime_status, t)}</p>
          <small className="table-secondary">{t('governanceUx.technicalStatusCode')}: <code>{runtime.runtime_status}</code></small>
          <p><strong>{t('governanceUx.scopeLabel')}:</strong> {governanceScopeLabel(summary.metric_scope, t)}</p>
          {summary.metric_scope ? <small className="table-secondary">{t('governanceUx.technicalCode')}: <code>{String(summary.metric_scope)}</code></small> : null}
          <p><strong>{t('governanceUx.complianceLabel')}:</strong> {localizedProductLabel(summary.compliance_ready, t)}</p>
          <p><strong>{t('governanceUx.governanceScoreLabel')}:</strong> {asText(runtime.compliance_readiness.governance_score, '0')}%</p>
        </div>
      </header>

      <section className="governance-classification-grid" aria-label={t('copy.governance_executive_summary_1742ec58')}>
        <article className={`metric-card governance-classification ${blockingCount > 0 ? 'is-blocking' : 'is-ready'}`}><small>{t('governanceUx.groups.operationalBlockers')}</small><strong>{blockingCount}</strong><p>{t(blockingCount > 0 ? 'governanceUx.operationalBlocked' : 'governanceUx.noOperationalBlockers')}</p></article>
        <article className={`metric-card governance-classification ${degradationCount > 0 ? 'is-degraded' : 'is-ready'}`}><small>{t('governanceUx.groups.nonBlockingDegradation')}</small><strong>{degradationCount}</strong><p>{t('governanceUx.groups.nonBlockingDegradationHelp')}</p></article>
        <article className={`metric-card governance-classification ${administrativeReviewCount > 0 ? 'is-review' : 'is-ready'}`}><small>{t('governanceUx.groups.administrativeReview')}</small><strong>{administrativeReviewCount}</strong><p>{t('governanceUx.groups.administrativeReviewHelp')}</p></article>
        <article className={`metric-card governance-classification ${governanceReady ? 'is-ready' : 'is-review'}`}><small>{t('governanceUx.governanceReadiness')}</small><strong>{t(governanceReady ? 'status.ready' : 'status.failed')}</strong><p>{t(governanceReady ? 'governanceUx.governanceReadyHelp' : 'governanceUx.governanceReviewHelp')}</p></article>
      </section>
      <DiagnosticsSection
        diagnostics={diagnostics}
        operationsAccess={operationsAccess}
        organizationId={organization?.id ?? null}
      />
      <details className="advanced-panel">
        <summary><LocalizedText id="copy.technical_evidence_audit_and_lineage_c56973ff" /></summary>
        <div className="advanced-panel-content">
          <SummaryCards runtime={runtime} />
          <AuditSection data={runtime.audit_governance} />
          <FeedbackSection data={runtime.feedback_governance} />
          <ClassificationRetentionSection classification={runtime.classification_governance} retention={runtime.retention_governance} />
          <PolicyEvidenceSection policy={runtime.policy_governance} evidence={runtime.runtime_evidence} />
          <LineageSection documentLineage={runtime.document_lineage} knowledgeLineage={runtime.knowledge_lineage} />
          <AssistantComplianceSection assistant={runtime.assistant_traceability} compliance={runtime.compliance_readiness} />
          <section className="table-card"><h2><LocalizedText id="copy.scope_classification_85fd4ec9" /></h2><p><LocalizedText id="copy.operational_and_operational_reference_records_are_in_4db101d2" /></p><div className="metrics-grid"><MetricCard label={t('copy.included_documents_0061b432')} value={asRecord(asRecord(summary.scope_classification).documents).included} /><MetricCard label={t('copy.excluded_validation_documents_f5d017ba')} value={asRecord(asRecord(summary.scope_classification).documents).excluded_validation} /><MetricCard label={t('copy.included_assistants_bd6db42f')} value={asRecord(asRecord(summary.scope_classification).assistants).included} /><MetricCard label={t('copy.excluded_non_operational_assistants_985ec77a')} value={asRecord(asRecord(summary.scope_classification).assistants).excluded_non_operational} /></div></section>
        </div>
      </details>
    </div>
  );
}
