'use client';

import { useI18n } from '../../i18n/I18nProvider';
import { LocalizedText } from '../layout/LocalizedText';

import { useEffect, useState } from 'react';

import { ReleaseGovernanceSection } from './ReleaseGovernanceSection';
import { CapacityLoadSection } from './CapacityLoadSection';
import { ObservabilitySection } from './ObservabilitySection';

import {
  activateRecoveryPolicy,
  addRecoveryBackupArtifact,
  completeRecoveryBackup,
  completeRecoveryRestore,
  completeRecoveryVerification,
  createRecoveryPolicy,
  createRecoveryVerification,
  getCapacityReadiness,
  getObservabilityReadiness,
  getProductionReadinessRuntime,
  getProductionWorkspaceRuntime,
  getRecoveryReadiness,
  registerRecoveryBackup,
  registerRecoveryRestore,
  runProductionAcceptance,
  type ProductionDomainSummary,
  type CapacityReadiness,
  type ObservabilityReadiness,
  type ProductionReadinessRuntime,
  type ProductionWorkspaceRuntime,
  type RecoveryReadiness,
} from '../../lib/production-readiness-api';
import { localizedProductLabel } from '../../lib/presentation';
import { PlatformApiError } from '../../lib/platform-api';

type Translate = (key: string, values?: Record<string, string | number | boolean | null | undefined>) => string;

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

function issueText(item: Record<string, unknown>, translate: Translate): string {
  return asText(item.message ?? item.label ?? item.reason ?? item.code, translate('dynamic.detailsAvailable'));
}

function actionLabel(action: Record<string, unknown> | undefined, translate: Translate): string {
  if (!action) return translate('dynamic.noActionRequired');

  const actionCode = String(action.action ?? action.action_key ?? '');
  const labelCode = String(action.label ?? '');

  if (
    actionCode === 'run_production_acceptance'
    || actionCode === 'resolve_local_product_acceptance_passed'
    || labelCode === 'resolve_local_product_acceptance_passed'
  ) {
    return translate('dynamic.runAcceptanceAndResolveGates');
  }

  return localizedProductLabel(
    action.label ?? action.action ?? action.action_key,
    translate,
    translate('dynamic.reviewTechnicalDetailsBelow'),
  );
}

function actionDestination(action: Record<string, unknown> | undefined): string | null {
  if (!action) return null;

  const actionCode = String(action.action ?? action.action_key ?? '');
  const domain = String(action.domain ?? '').toLowerCase();

  if (
    actionCode === 'run_production_acceptance'
    || actionCode === 'resolve_local_product_acceptance_passed'
  ) {
    return '#production-acceptance';
  }

  if (domain === 'security') return '/security';

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

function functionalStatus(status: unknown, translate: Translate): string {
  const value = String(status ?? 'not_evaluated').toLowerCase();
  if (value === 'passed' || value === 'ready') return translate('dynamic.healthy');
  if (value === 'blocked') return translate('status.blocked');
  if (value === 'failed') return translate('copy.degraded_13c27ff8');
  if (value === 'expired') return translate('status.expired');
  if (value === 'stale') return translate('copy.stale_189cc40c');
  if (value === 'interrupted') return translate('dynamic.interrupted');
  if (value === 'not_evaluated') return translate('status.notEvaluated');
  return translate('dynamic.warning');
}

function Summary({
  runtime,
  workspace,
}: {
  runtime: ProductionReadinessRuntime;
  workspace: ProductionWorkspaceRuntime | null;
}) {
  const { t } = useI18n();
  const acceptance = runtime.product_acceptance ?? {};
  const freshness = runtime.evidence_freshness ?? {};
  const eligibility = runtime.release_eligibility ?? {};
  const nextAction = workspace?.next_actions[0] ?? runtime.next_actions[0];
  const nextActionDestination = actionDestination(nextAction);
  return (
    <section className="table-card" data-production-readiness-section="summary">
      <h2><LocalizedText id="copy.release_decision_a8334061" /></h2>
      <p><LocalizedText id="copy.the_current_decision_uses_the_authoritative_eligibil_e363d9af" /></p>
      <div className="metrics-grid">
        <article className="metric-card">
          <small><LocalizedText id="copy.overall_release_eligibility_3f160534" /></small>
          <strong>{localizedProductLabel(eligibility.status ?? 'unavailable', t)}</strong>
        </article>
        <article className="metric-card">
          <small><LocalizedText id="copy.product_acceptance_0826d08b" /></small>
          <strong>{localizedProductLabel(acceptance.status ?? runtime.runtime_status, t)}</strong>
        </article>
        <article className="metric-card">
          <small><LocalizedText id="copy.evidence_freshness_56563eff" /></small>
          <strong>{localizedProductLabel(freshness.status ?? 'unavailable', t)}</strong>
        </article>
        <article className="metric-card">
          <small><LocalizedText id="copy.blocking_issues_c74144eb" /></small>
          <strong>{runtime.blockers.length}</strong>
        </article>
        <article className="metric-card">
          <small><LocalizedText id="copy.recommended_next_action_ec237d23" /></small>
          <strong>{nextActionDestination ? <a className="text-link" href={nextActionDestination}>{actionLabel(nextAction, t)}</a> : actionLabel(nextAction, t)}</strong>
          {nextAction && !nextActionDestination ? <span className="muted-text"><LocalizedText id="copy.review_the_technical_details_below_d2e80c78" /></span> : null}
        </article>
      </div>
      {runtime.blockers.length > 0 ? (
        <div className="context-card">
          <strong><LocalizedText id="copy.why_the_release_requires_attention_9983f2b9" /></strong>
          <ul className="compact-list">
            {runtime.blockers.slice(0, 3).map((item, index) => <li key={`primary-blocker-${index}`}>{issueText(item, t)}</li>)}
          </ul>
          {runtime.blockers.length > 3 ? <p className="muted-text">{t('dynamic.additionalBlockingIssues', { count: runtime.blockers.length - 3 })}</p> : null}
        </div>
      ) : null}
    </section>
  );
}

function AcceptanceSummary({
  workspace,
  onRun,
  running,
  actionError,
  canAdminister,
}: {
  workspace: ProductionWorkspaceRuntime | null;
  onRun: () => void;
  running: boolean;
  actionError: string | null;
  canAdminister: boolean;
}) {
  const { t, date } = useI18n();
  if (!workspace) {
    return (
      <section className="card" data-production-acceptance-section="empty" id="production-acceptance">
        <h2><LocalizedText id="copy.production_acceptance_foundation_4e0a9a13" /></h2>
        <p><LocalizedText id="copy.production_acceptance_evidence_is_not_available_for__6d7c1be8" /></p>
      </section>
    );
  }
  const latestRun = workspace.latest_run;
  const acceptance = workspace.product_acceptance ?? {};
  return (
    <section className="table-card" data-production-acceptance-section="summary" id="production-acceptance">
      <div className="context-card-header">
        <h2><LocalizedText id="copy.product_acceptance_evaluation_9380f050" /></h2>
        {canAdminister ? <button className="secondary-button" type="button" onClick={onRun} disabled={running}>
          {running ? <LocalizedText id="copy.evaluating_101c0592" /> : <LocalizedText id="copy.run_production_acceptance_65fe5e49" />}
        </button> : null}
      </div>
      <div className="metrics-grid">
        <MetricCard label={t('copy.historical_product_acceptance_result_c8abb4d9')} value={acceptance.historical_result ?? latestRun?.status ?? t('copy.no_run_2c43a92c')} />
        <MetricCard label={t('copy.mandatory_passed_b9672147')} value={workspace.mandatory_gate_counts.passed ?? 0} />
        <MetricCard label={t('copy.mandatory_blocked_6fea6b81')} value={workspace.mandatory_gate_counts.blocked ?? 0} />
        <MetricCard label={t('copy.last_evaluation_00adcf45')} value={latestRun?.evaluated_at ? date(latestRun.evaluated_at, { dateStyle: 'medium', timeStyle: 'short' }) : t('copy.no_run_2c43a92c')} />
      </div>
      {actionError ? <p className="form-error">{actionError}</p> : null}
      <p>
        <LocalizedText id="copy.historical_results_remain_visible_for_traceability_o_e0f1c322" /></p>
    </section>
  );
}

function AcceptanceDomains({ domains }: { domains: ProductionDomainSummary[] }) {
  const { t, duration } = useI18n();
  return (
    <section className="table-card" data-production-acceptance-section="domains">
      <h2><LocalizedText id="copy.production_acceptance_domains_217f9ce1" /></h2>
      {domains.length > 0 ? (
        <table>
          <thead>
            <tr>
              <th><LocalizedText id="copy.domain_9b10914d" /></th>
              <th><LocalizedText id="common.status" /></th>
              <th><LocalizedText id="copy.mandatory_4c2ea2d1" /></th>
              <th><LocalizedText id="copy.passed_271d60f4" /></th>
              <th><LocalizedText id="copy.failed_09fef5d8" /></th>
              <th><LocalizedText id="status.blocked" /></th>
              <th><LocalizedText id="status.notEvaluated" /></th>
              <th><LocalizedText id="copy.blockers_699edf83" /></th>
              <th><LocalizedText id="copy.warnings_1430f976" /></th>
              <th><LocalizedText id="copy.evidence_age_fb037192" /></th>
              <th><LocalizedText id="copy.evidence_origin_8417a416" /></th>
            </tr>
          </thead>
          <tbody>
            {domains.map((domain) => (
              <tr key={domain.domain}>
                <td>{domain.domain}</td>
                <td>{functionalStatus(domain.status, t)}</td>
                <td>{domain.mandatory_total}</td>
                <td>{domain.passed}</td>
                <td>{domain.failed}</td>
                <td>{domain.blocked}</td>
                <td>{domain.not_evaluated}</td>
                <td>{domain.blockers.length}</td>
                <td>{domain.warnings.length}</td>
                <td>{domain.evidence_age_seconds === null || domain.evidence_age_seconds === undefined ? <LocalizedText id="copy.no_evidence_fade4ede" /> : duration(domain.evidence_age_seconds * 1000)}</td>
                <td>{domain.evidence_origins.join(', ') || t('copy.no_evidence_fade4ede')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p><LocalizedText id="copy.no_production_acceptance_run_has_been_evaluated_yet_03f7eace" /></p>
      )}
    </section>
  );
}

function OperationalAcceptance({ workspace }: { workspace: ProductionWorkspaceRuntime | null }) {
  const { t } = useI18n();
  const operational = asRecord(workspace?.operational_readiness);
  const gates = asList(operational.gates);
  const diagnostics = asList(operational.diagnostics);
  const blockers = asList(operational.blocking_issues);
  return (
    <section className="table-card" data-production-acceptance-section="operational">
      <h2><LocalizedText id="copy.operational_acceptance_dc1bd1ab" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.operational_status_1fdea4e2')} value={operational.status ?? t('copy.not_evaluated_a081a2c7')} />
        <MetricCard label={t('copy.operational_ready_e89fa692')} value={operational.operational_ready ?? false} />
        <MetricCard label={t('copy.operational_gates_6b458477')} value={gates.length} />
        <MetricCard label={t('copy.open_blockers_5c3bbb2d')} value={blockers.length} />
        <MetricCard label={t('copy.diagnostics_3af2279f')} value={diagnostics.length} />
      </div>
      <table>
        <thead>
          <tr>
            <th><LocalizedText id="copy.gate_5701b5f6" /></th>
            <th><LocalizedText id="common.status" /></th>
            <th><LocalizedText id="copy.summary_12b71c3e" /></th>
          </tr>
        </thead>
        <tbody>
          {gates.map((gate) => (
            <tr key={asText(gate.gate_code)}>
              <td>{asText(gate.gate_code)}</td>
              <td>{functionalStatus(asText(gate.status), t)}</td>
              <td>{asText(gate.summary)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function SecurityAcceptance({ workspace }: { workspace: ProductionWorkspaceRuntime | null }) {
  const { t } = useI18n();
  const security = asRecord(workspace?.security_readiness);
  const gates = asList(security.gates);
  const blockers = asList(security.blockers);
  const findings = asList(security.findings);
  return (
    <section className="table-card" data-production-acceptance-section="security">
      <h2><LocalizedText id="copy.security_acceptance_803054f8" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.security_status_bf049782')} value={security.status ?? t('copy.not_evaluated_a081a2c7')} />
        <MetricCard label={t('copy.security_ready_96fddb06')} value={security.security_ready ?? false} />
        <MetricCard label={t('copy.security_gates_1d04951b')} value={gates.length} />
        <MetricCard label={t('copy.open_blockers_5c3bbb2d')} value={blockers.length} />
        <MetricCard label={t('copy.findings_ca9b7e7e')} value={findings.length} />
      </div>
      <table>
        <thead>
          <tr>
            <th><LocalizedText id="copy.gate_5701b5f6" /></th>
            <th><LocalizedText id="common.status" /></th>
            <th><LocalizedText id="copy.evidence_7ea014de" /></th>
            <th><LocalizedText id="copy.summary_12b71c3e" /></th>
          </tr>
        </thead>
        <tbody>
          {gates.map((gate) => (
            <tr key={asText(gate.gate_code)}>
              <td>{asText(gate.gate_code).replaceAll('_', ' ')}</td>
              <td>{functionalStatus(asText(gate.status), t)}</td>
              <td>{asText(gate.evidence_type)}</td>
              <td>{asText(gate.summary)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function ConfigurationPreflight({ workspace }: { workspace: ProductionWorkspaceRuntime | null }) {
  const { t } = useI18n();
  const preflight = workspace?.configuration_preflight;
  return (
    <section className="table-card" data-production-acceptance-section="preflight">
      <h2><LocalizedText id="copy.configuration_preflight_3fe9a1bb" /></h2>
      {preflight ? (
        <table>
          <thead>
            <tr>
              <th><LocalizedText id="copy.check_4b5e84be" /></th>
              <th><LocalizedText id="common.status" /></th>
              <th><LocalizedText id="copy.value_8dce170d" /></th>
              <th><LocalizedText id="copy.reason_f219cc06" /></th>
            </tr>
          </thead>
          <tbody>
            {preflight.checks.map((check) => (
              <tr key={check.setting_code}>
                <td>{check.setting_code.replaceAll('_', ' ')}</td>
                <td>{functionalStatus(check.status, t)}</td>
                <td>{check.masked_value}</td>
                <td>{check.reason.replaceAll('_', ' ')}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p><LocalizedText id="copy.configuration_preflight_is_not_available_for_the_cur_81c2a1c5" /></p>
      )}
    </section>
  );
}

function NextActions({ workspace }: { workspace: ProductionWorkspaceRuntime | null }) {
  const { t } = useI18n();
  const actions = workspace?.next_actions ?? [];
  const grouped = actions.reduce<Record<string, typeof actions>>((groups, action) => {
    const domain = String(action.domain ?? action.type ?? t('dynamic.general'));
    groups[domain] = [...(groups[domain] ?? []), action];
    return groups;
  }, {});
  return (
    <section className="table-card" data-production-acceptance-section="next-actions">
      <h2><LocalizedText id="copy.detailed_next_actions_5bb3ab58" /></h2>
      {actions.length > 0 ? (
        <div className="alerts-grid">{Object.entries(grouped).map(([domain, domainActions]) => <article className="context-card" key={domain}><strong>{localizedProductLabel(domain, t)}</strong><ul className="compact-list">{domainActions.map((action, index) => {
          const destination = actionDestination(action);
          return <li key={`${asText(action.action_key)}-${index}`}>{destination ? <a className="text-link" href={destination}>{actionLabel(action, t)}</a> : t('dynamic.actionWithReviewDetails', { action: actionLabel(action, t) })}</li>;
        })}</ul></article>)}</div>
      ) : (
        <p><LocalizedText id="copy.no_production_acceptance_actions_are_currently_requi_35f5e056" /></p>
      )}
    </section>
  );
}

function RecoverySection({
  recovery,
  actionError,
  actionRunning,
  canAdminister,
  onCreatePolicy,
  onRegisterBackup,
  onAddArtifact,
  onCompleteBackup,
  onRegisterRestore,
  onCompleteRestore,
  onCreateVerification,
  onCompleteVerification,
}: {
  recovery: RecoveryReadiness | null;
  actionError: string | null;
  actionRunning: boolean;
  canAdminister: boolean;
  onCreatePolicy: (payload: Record<string, unknown>) => void;
  onRegisterBackup: (payload: Record<string, unknown>) => void;
  onAddArtifact: (resourceType: string, checksum: string) => void;
  onCompleteBackup: () => void;
  onRegisterRestore: (payload: Record<string, unknown>) => void;
  onCompleteRestore: () => void;
  onCreateVerification: () => void;
  onCompleteVerification: () => void;
}) {
  const { t } = useI18n();
  const [policyName, setPolicyName] = useState('Platform Recovery Policy');
  const [rpoMinutes, setRpoMinutes] = useState('60');
  const [rtoMinutes, setRtoMinutes] = useState('240');
  const [evidenceAge, setEvidenceAge] = useState('168');
  const [manifestHash, setManifestHash] = useState('');
  const [artifactChecksum, setArtifactChecksum] = useState('');
  const activePolicy = recovery?.active_policy;
  const latestBackup = recovery?.latest_backup;
  const latestRestore = recovery?.latest_restore;
  const latestVerification = recovery?.latest_restore_verification;
  return (
    <section className="table-card" data-production-acceptance-section="recovery">
      <div className="context-card-header">
        <h2><LocalizedText id="copy.recovery_evidence_runtime_5453e054" /></h2>
        <span>{functionalStatus(recovery?.status ?? 'not_evaluated', t)}</span>
      </div>
      <div className="metrics-grid">
        <MetricCard label={t('copy.active_policy_e5bd57e3')} value={activePolicy?.name ?? t('status.notConfigured')} />
        <MetricCard label={t('copy.latest_backup_608da1da')} value={latestBackup?.status ?? t('copy.no_backup_c6b12a6d')} />
        <MetricCard label={t('copy.latest_restore_dc3ba639')} value={latestRestore?.status ?? t('copy.no_restore_c0d304c7')} />
        <MetricCard label={t('copy.verification_03128bed')} value={latestVerification?.status ?? t('copy.no_verification_41c637f6')} />
      </div>
      {actionError ? <p className="form-error">{actionError}</p> : null}
      {canAdminister ? <div className="alerts-grid">
        <article className="context-card">
          <strong><LocalizedText id="copy.policy_bb9cf141" /></strong>
          <label>
            <LocalizedText id="common.name" />
            <input value={policyName} onChange={(event) => setPolicyName(event.target.value)} />
          </label>
          <label>
            <LocalizedText id="dynamic.rpoMinutes" />
            <input value={rpoMinutes} onChange={(event) => setRpoMinutes(event.target.value)} />
          </label>
          <label>
            <LocalizedText id="dynamic.rtoMinutes" />
            <input value={rtoMinutes} onChange={(event) => setRtoMinutes(event.target.value)} />
          </label>
          <label>
            <LocalizedText id="dynamic.evidenceMaxAgeHours" />
            <input value={evidenceAge} onChange={(event) => setEvidenceAge(event.target.value)} />
          </label>
          <button
            className="secondary-button"
            type="button"
            disabled={actionRunning}
            onClick={() =>
              onCreatePolicy({
                scope: 'platform',
                name: policyName,
                provider_type: 'external_evidence',
                database_backup_enabled: true,
                object_storage_backup_enabled: true,
                configuration_backup_enabled: true,
                rpo_minutes: Number(rpoMinutes),
                rto_minutes: Number(rtoMinutes),
                evidence_max_age_hours: Number(evidenceAge),
                verification_required: true,
              })
            }
          >
            <LocalizedText id="copy.create_and_activate_policy_adc45c58" /></button>
        </article>
        <article className="context-card">
          <strong><LocalizedText id="copy.backup_evidence_bb7e1f43" /></strong>
          <label>
            <LocalizedText id="dynamic.manifestHash" />
            <input value={manifestHash} onChange={(event) => setManifestHash(event.target.value)} />
          </label>
          <label>
            <LocalizedText id="dynamic.artifactChecksum" />
            <input value={artifactChecksum} onChange={(event) => setArtifactChecksum(event.target.value)} />
          </label>
          <button
            className="secondary-button"
            type="button"
            disabled={actionRunning || !activePolicy || !manifestHash}
            onClick={() =>
              onRegisterBackup({
                scope: 'platform',
                policy_id: activePolicy?.id,
                provider_type: 'external_evidence',
                idempotency_key: `portal-backup-${activePolicy?.id}`,
                backup_type: 'external',
                database_included: true,
                object_storage_included: true,
                configuration_included: true,
                consistent_snapshot: true,
                manifest_hash: manifestHash,
              })
            }
          >
            <LocalizedText id="copy.register_backup_aa88faa9" /></button>
          <button className="secondary-button" type="button" disabled={actionRunning || !latestBackup} onClick={() => onAddArtifact('postgresql', artifactChecksum)}>
            <LocalizedText id="copy.add_database_artifact_60648099" /></button>
          <button className="secondary-button" type="button" disabled={actionRunning || !latestBackup} onClick={() => onAddArtifact('object_storage', artifactChecksum)}>
            <LocalizedText id="copy.add_object_storage_artifact_86f15bcc" /></button>
          <button className="secondary-button" type="button" disabled={actionRunning || !latestBackup} onClick={() => onAddArtifact('application_configuration', artifactChecksum)}>
            <LocalizedText id="copy.add_configuration_artifact_5b599ae5" /></button>
          <button className="secondary-button" type="button" disabled={actionRunning || !latestBackup} onClick={onCompleteBackup}>
            <LocalizedText id="copy.complete_backup_4d622d02" /></button>
        </article>
        <article className="context-card">
          <strong><LocalizedText id="copy.restore_and_verification_381f3bd4" /></strong>
          <button
            className="secondary-button"
            type="button"
            disabled={actionRunning || !activePolicy || !latestBackup}
            onClick={() =>
              onRegisterRestore({
                scope: 'platform',
                policy_id: activePolicy?.id,
                backup_execution_id: latestBackup?.id,
                provider_type: 'external_evidence',
                idempotency_key: `portal-restore-${latestBackup?.id}`,
                restore_target_type: 'isolated_validation_environment',
                destructive_operation: false,
              })
            }
          >
            <LocalizedText id="copy.register_restore_3925434e" /></button>
          <button className="secondary-button" type="button" disabled={actionRunning || !latestRestore} onClick={onCompleteRestore}>
            <LocalizedText id="copy.complete_restore_fdcf9ae6" /></button>
          <button className="secondary-button" type="button" disabled={actionRunning || !latestRestore} onClick={onCreateVerification}>
            <LocalizedText id="copy.start_verification_8b397fa7" /></button>
          <button className="secondary-button" type="button" disabled={actionRunning || !latestVerification || latestVerification.status !== 'running'} onClick={onCompleteVerification}>
            <LocalizedText id="copy.complete_verification_3ac08266" /></button>
        </article>
      </div> : null}
      <div className="alerts-grid">
        {(recovery?.gates ?? []).map((gate) => (
          <article className="context-card" key={asText(gate.gate_code)}>
            <div className="context-card-header">
              <strong>{asText(gate.gate_code).replaceAll('_', ' ')}</strong>
              <span>{functionalStatus(gate.status, t)}</span>
            </div>
            <p>{asText(gate.summary)}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function GateMatrix({ runtime }: { runtime: ProductionReadinessRuntime }) {
  return (
    <section className="table-card" data-production-readiness-section="gate-matrix">
      <h2><LocalizedText id="copy.production_gate_matrix_4f701292" /></h2>
      <table>
        <thead>
          <tr><th><LocalizedText id="copy.gate_5701b5f6" /></th><th><LocalizedText id="common.status" /></th><th><LocalizedText id="copy.domain_9b10914d" /></th><th><LocalizedText id="copy.source_6da13add" /></th><th><LocalizedText id="copy.blocker_7ed53365" /></th></tr>
        </thead>
        <tbody>
          {runtime.gate_matrix.map((gate) => (
            <tr key={asText(gate.gate_code)}>
              <td>{asText(gate.gate_code)}</td>
              <td>{asText(gate.status)}</td>
              <td>{asText(gate.domain)}</td>
              <td><small>{asText(gate.evidence_origin)}</small></td>
              <td>{gate.blocker_code ? 1 : 0}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function DomainReadiness({ runtime }: { runtime: ProductionReadinessRuntime }) {
  return (
    <section className="table-card" data-production-readiness-section="domains">
      <h2><LocalizedText id="copy.domain_readiness_4f5c88b6" /></h2>
      <div className="alerts-grid">
        {runtime.evidence_contracts.map((contract) => (
            <article className="context-card" key={contract.domain}>
              <div className="context-card-header">
                <strong>{contract.domain}</strong>
                <span>{contract.status}</span>
              </div>
              <ul className="compact-list">
                <li><strong><LocalizedText id="copy.contract_5a0ba3bb" /></strong>: {contract.contract_version}</li>
                <li><strong><LocalizedText id="copy.runtime_c4740e4c" /></strong>: {contract.runtime_version}</li>
                <li><strong><LocalizedText id="copy.evaluated_d8033d01" /></strong>: {contract.evaluation_timestamp}</li>
                <li><strong><LocalizedText id="copy.expires_a99be3da" /></strong>: {contract.expires_at ?? <LocalizedText id="copy.not_applicable_79acc720" />}</li>
                <li><strong><LocalizedText id="copy.origin_44ab85a2" /></strong>: {contract.evidence_origin}</li>
              </ul>
            </article>
        ))}
      </div>
    </section>
  );
}

function Diagnostics({ runtime }: { runtime: ProductionReadinessRuntime }) {
  const { t } = useI18n();
  const groups = [
    [t('copy.blocking_findings_5035b077'), runtime.blockers],
    [t('copy.warnings_1430f976'), runtime.warnings],
    [t('copy.recommendations_4faa65b5'), runtime.recommendations],
  ];
  return (
    <section className="table-card" data-production-readiness-section="diagnostics">
      <h2><LocalizedText id="copy.operational_diagnostics_a65ef889" /></h2>
      <p><LocalizedText id="copy.blocking_gates_are_mandatory_release_decisions_block_ae8d43fd" /></p>
      <div className="metrics-grid">
        <MetricCard label={t('copy.side_effects_f9b9f592')} value={t(runtime.side_effects_performed ? 'copy.performed_81b8fce9' : 'copy.not_performed_0c6a8939')} />
        <MetricCard label={t('copy.external_calls_2326bb0c')} value={t(runtime.external_calls_performed ? 'copy.detected_74fb2cc6' : 'copy.not_detected_a5cb42ba')} />
        <MetricCard label={t('copy.qdrant_388a01a6')} value={t(runtime.qdrant_used ? 'copy.used_02c0e4a1' : 'copy.not_used_72a86113')} />
        <MetricCard label={t('copy.blocking_findings_5035b077')} value={runtime.blockers.length} />
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

export function ProductionReadinessCenter({ canAdminister }: { canAdminister: boolean }) {
  const { t, date } = useI18n();
  const [runtime, setRuntime] = useState<ProductionReadinessRuntime | null>(null);
  const [workspace, setWorkspace] = useState<ProductionWorkspaceRuntime | null>(null);
  const [recovery, setRecovery] = useState<RecoveryReadiness | null>(null);
  const [capacity, setCapacity] = useState<CapacityReadiness | null>(null);
  const [observability, setObservability] = useState<ObservabilityReadiness | null>(null);
  const [recoveryError, setRecoveryError] = useState<string | null>(null);
  const [capacityError, setCapacityError] = useState<string | null>(null);
  const [observabilityError, setObservabilityError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [workspaceLoading, setWorkspaceLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [runningAcceptance, setRunningAcceptance] = useState(false);
  const [runningRecoveryAction, setRunningRecoveryAction] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setWorkspaceLoading(true);
      setError(null);
      setForbidden(false);
      setWorkspaceError(null);
      setRecoveryError(null);
      setCapacityError(null);
      setObservabilityError(null);
      try {
        const [payload, workspacePayload, recoveryPayload, capacityPayload, observabilityPayload] = await Promise.allSettled([
          getProductionReadinessRuntime(),
          getProductionWorkspaceRuntime(),
          getRecoveryReadiness(),
          getCapacityReadiness(),
          getObservabilityReadiness(),
        ]);
        if (payload.status === 'fulfilled' && !cancelled) setRuntime(payload.value);
        if (payload.status === 'rejected' && !cancelled) {
          setForbidden(payload.reason instanceof PlatformApiError && payload.reason.status === 403);
          setError(payload.reason instanceof Error ? payload.reason.message : t('dynamic.productionReadinessUnavailable'));
        }
        if (workspacePayload.status === 'fulfilled' && !cancelled) setWorkspace(workspacePayload.value);
        if (workspacePayload.status === 'rejected' && !cancelled) {
          setWorkspaceError(
            workspacePayload.reason instanceof Error
              ? workspacePayload.reason.message
              : t('dynamic.acceptanceFoundationUnavailable'),
          );
        }
        if (recoveryPayload.status === 'fulfilled' && !cancelled) setRecovery(recoveryPayload.value);
        if (recoveryPayload.status === 'rejected' && !cancelled) {
          setRecoveryError(recoveryPayload.reason instanceof Error ? recoveryPayload.reason.message : t('dynamic.recoveryReadinessUnavailable'));
        }
        if (capacityPayload.status === 'fulfilled' && !cancelled) setCapacity(capacityPayload.value);
        if (capacityPayload.status === 'rejected' && !cancelled) {
          setCapacityError(capacityPayload.reason instanceof Error ? capacityPayload.reason.message : t('dynamic.capacityReadinessUnavailable'));
        }
        if (observabilityPayload.status === 'fulfilled' && !cancelled) setObservability(observabilityPayload.value);
        if (observabilityPayload.status === 'rejected' && !cancelled) {
          setObservabilityError(observabilityPayload.reason instanceof Error ? observabilityPayload.reason.message : t('dynamic.observabilityReadinessUnavailable'));
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(
            loadError instanceof Error
              ? loadError.message
              : t('dynamic.productionReadinessUnavailable'),
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
        if (!cancelled) setWorkspaceLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [reloadToken, t]);

  if (loading) {
    return (
      <section className="card workspace-state" data-production-readiness-section="loading" role="status">
        <span className="eyebrow"><LocalizedText id="pages.production.title" /></span>
        <h2><LocalizedText id="copy.evaluating_platform_evidence_25a27447" /></h2>
        <p><LocalizedText id="copy.evaluating_platform_evidence_this_may_take_a_few_sec_5515fca1" /></p>
        <div className="metrics-grid" aria-hidden="true">
          {['copy.overall_release_eligibility_3f160534', 'copy.product_acceptance_0826d08b', 'copy.evidence_freshness_56563eff', 'copy.blocking_issues_c74144eb', 'copy.recommended_next_action_ec237d23'].map((labelKey) => (
            <article className="metric-card" key={labelKey}><small>{t(labelKey)}</small><strong>—</strong></article>
          ))}
        </div>
      </section>
    );
  }

  if (error || !runtime) {
    return (
      <section className="card" data-production-readiness-section={forbidden ? 'forbidden' : 'failed'}>
        <h2>{forbidden ? <LocalizedText id="copy.production_readiness_access_forbidden_d08a7ab2" /> : <LocalizedText id="copy.production_readiness_center_unavailable_175ee7d6" />}</h2>
        <p>{forbidden ? <LocalizedText id="copy.platformPermissionRequired" /> : error ?? <LocalizedText id="copy.no_production_readiness_runtime_payload_was_returned_f222a183" />}</p>
        {!forbidden ? <button className="button secondary" type="button" onClick={() => setReloadToken((value) => value + 1)}><LocalizedText id="common.actions.retry" /></button> : null}
      </section>
    );
  }

  async function handleRunAcceptance() {
    if (runningAcceptance) return;
    setRunningAcceptance(true);
    setWorkspaceError(null);
    try {
      await runProductionAcceptance({
        scope: 'platform',
        idempotency_key: `portal-production-acceptance-${Date.now()}`,
        requested_by: 'production-portal',
      });
      const [refreshedWorkspace, refreshedRuntime] = await Promise.all([
        getProductionWorkspaceRuntime(),
        getProductionReadinessRuntime(),
      ]);
      setWorkspace(refreshedWorkspace);
      setRuntime(refreshedRuntime);
    } catch (runError) {
      setWorkspaceError(
        runError instanceof Error
          ? runError.message
          : t('dynamic.acceptanceEvaluationFailed'),
      );
    } finally {
      setRunningAcceptance(false);
    }
  }

  async function refreshRecovery() {
    const [recoveryPayload, workspacePayload] = await Promise.all([getRecoveryReadiness(), getProductionWorkspaceRuntime()]);
    setRecovery(recoveryPayload);
    setWorkspace(workspacePayload);
  }

  async function runRecoveryAction(action: () => Promise<unknown>) {
    if (runningRecoveryAction) return;
    setRunningRecoveryAction(true);
    setWorkspaceError(null);
    try {
      await action();
      await refreshRecovery();
    } catch (runError) {
      setWorkspaceError(runError instanceof Error ? runError.message : t('dynamic.recoveryActionPersistenceFailed'));
    } finally {
      setRunningRecoveryAction(false);
    }
  }

  return (
    <div className="stack" data-production-readiness-status={runtime.runtime_status}>
      <header className="platform-hero">
        <div>
          <span className="badge"><LocalizedText id="pages.production.title" /></span>
          <h1><LocalizedText id="copy.release_decision_a8334061" /></h1>
          <p><LocalizedText id="copy.executive_release_decision_based_on_persisted_platfo_a47872fe" /></p>
        </div>
        <div className="platform-status-panel">
          <p>{t('dynamic.historicalEvaluation', { status: localizedProductLabel(runtime.runtime_status, t) })}</p>
          <p><LocalizedText id="copy.scope_platform_release_190b33dc" /></p>
          <p>{t('dynamic.lastEvaluated', { date: date(runtime.evaluation_timestamp, { dateStyle: 'medium', timeStyle: 'short' }) })}</p>
          <p>{t('dynamic.evidenceValidUntil', { date: runtime.expires_at ? date(runtime.expires_at, { dateStyle: 'medium', timeStyle: 'short' }) : t('copy.no_expiry_reported_0ddc78e7') })}</p>
        </div>
      </header>
      {runtime.evidence_contracts.length === 0 ? (
        <section className="card" data-production-readiness-section="empty">
          <h2><LocalizedText id="copy.production_readiness_is_not_evaluated_4bea0776" /></h2>
          <p><LocalizedText id="copy.run_production_acceptance_to_persist_the_authoritati_d9cb5b0d" /></p>
        </section>
      ) : null}
      <Summary runtime={runtime} workspace={workspace} />
      {workspaceLoading ? (
        <section className="card workspace-state" data-production-acceptance-section="loading" role="status">
          <h2><LocalizedText id="copy.evaluating_product_acceptance_evidence_63cc7ed9" /></h2>
          <p><LocalizedText id="copy.evaluating_platform_evidence_this_may_take_a_few_sec_5515fca1" /></p>
          <div className="metrics-grid" aria-hidden="true">
            {['copy.historical_product_acceptance_result_c8abb4d9', 'copy.mandatory_passed_b9672147', 'copy.mandatory_blocked_6fea6b81'].map((labelKey) => (
              <article className="metric-card" key={labelKey}><small>{t(labelKey)}</small><strong>—</strong></article>
            ))}
          </div>
        </section>
      ) : workspaceError && !workspace ? (
        <section className="card" data-production-acceptance-section={workspaceError.startsWith('You do not have permission') ? 'forbidden' : 'failed'}>
          <h2><LocalizedText id="copy.production_acceptance_unavailable_4e1baef5" /></h2>
          <p>{workspaceError}</p>
        </section>
      ) : (
        <>
          <AcceptanceSummary
            workspace={workspace}
            onRun={handleRunAcceptance}
            running={runningAcceptance}
            actionError={workspaceError}
            canAdminister={canAdminister}
          />
        </>
      )}
      <details className="advanced-panel" id="technical-release-details">
        <summary><LocalizedText id="copy.technical_gates_evidence_and_recovery_controls_1e709ef8" /></summary>
        <div className="advanced-panel-content">
          <NextActions workspace={workspace} />
          <Diagnostics runtime={runtime} />
          {canAdminister ? <ReleaseGovernanceSection /> : null}
          <AcceptanceDomains domains={workspace?.domain_summary ?? []} />
          <OperationalAcceptance workspace={workspace} />
          <SecurityAcceptance workspace={workspace} />
          <ConfigurationPreflight workspace={workspace} />
          <CapacityLoadSection capacity={capacity} error={capacityError} />
          <ObservabilitySection observability={observability} error={observabilityError} />
          {recoveryError ? <section className="card"><h2><LocalizedText id="copy.recovery_readiness_unavailable_41146e69" /></h2><p>{recoveryError}</p></section> : null}
          {!recoveryError ? <RecoverySection
            recovery={recovery}
            actionError={workspaceError}
            actionRunning={runningRecoveryAction}
            canAdminister={canAdminister}
            onCreatePolicy={(payload) => runRecoveryAction(async () => { const policy = await createRecoveryPolicy(payload); await activateRecoveryPolicy(policy.id); })}
            onRegisterBackup={(payload) => runRecoveryAction(() => registerRecoveryBackup(payload))}
            onAddArtifact={(resourceType, checksum) => runRecoveryAction(() => addRecoveryBackupArtifact(recovery?.latest_backup?.id ?? '', { artifact_type: `${resourceType}_artifact`, resource_type: resourceType, storage_location_masked: 'external_evidence_registered', checksum_algorithm: 'sha256', checksum: checksum || undefined, verification_status: 'verified' }))}
            onCompleteBackup={() => runRecoveryAction(() => completeRecoveryBackup(recovery?.latest_backup?.id ?? '', { manifest_hash: recovery?.latest_backup?.manifest_hash, consistent_snapshot: true }))}
            onRegisterRestore={(payload) => runRecoveryAction(() => registerRecoveryRestore(payload))}
            onCompleteRestore={() => runRecoveryAction(() => completeRecoveryRestore(recovery?.latest_restore?.id ?? '', { database_restored: true, object_storage_restored: true, configuration_restored: true }))}
            onCreateVerification={() => runRecoveryAction(() => createRecoveryVerification(recovery?.latest_restore?.id ?? '', { verification_type: 'external_evidence', verified_by: 'production-portal' }))}
            onCompleteVerification={() => runRecoveryAction(() => completeRecoveryVerification(recovery?.latest_restore_verification?.id ?? '', { database_connectivity_verified: true, schema_version_verified: true, record_counts_verified: true, object_storage_access_verified: true, artifact_checksums_verified: true, organization_isolation_verified: true, knowledge_lineage_verified: true, enterprise_search_verified: true, conversation_persistence_verified: true, verified_by: 'production-portal', verification_payload: { source: 'external_evidence' } }))}
          /> : null}
          <GateMatrix runtime={runtime} />
          <DomainReadiness runtime={runtime} />
        </div>
      </details>
    </div>
  );
}
