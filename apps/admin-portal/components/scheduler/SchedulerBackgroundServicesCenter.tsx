'use client';

import { useI18n } from '../../i18n/I18nProvider';

import { LocalizedText } from '../layout/LocalizedText';

import { useEffect, useState } from 'react';

import {
  getSchedulerBackgroundServicesRuntime,
  type SchedulerBackgroundServicesRuntime,
} from '../../lib/scheduler-background-services-api';
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

function MetricCard({ label, value }: { label: string; value: unknown }) {
  const { t } = useI18n();
  return (
    <article className="metric-card">
      <small>{label}</small>
      <strong>{localizedProductLabel(value, t, '0')}</strong>
    </article>
  );
}

function Summary({ runtime }: { runtime: SchedulerBackgroundServicesRuntime }) {
  const { t } = useI18n();
  const summary = runtime.workspace_summary ?? {};
  const readiness = runtime.runtime_readiness ?? {};
  return (
    <section className="grid" data-scheduler-center-section="summary">
      <article className="card health-card">
        <div className="context-card-header">
          <h2><LocalizedText id="copy.background_services_7ded584b" /></h2>
          <span className={statusClass(readiness.overall_runtime_readiness === 'ready')}></span>
        </div>
        <span className="metric-value">{localizedProductLabel(readiness.overall_runtime_readiness, t)}</span>
      </article>
      <MetricCard label={t('copy.scheduler_cdcb4d84')} value={summary.scheduler_ready} />
      <MetricCard label={t('copy.workers_b6ef3acd')} value={summary.workers_ready} />
      <MetricCard label={t('copy.runtime_c4740e4c')} value={summary.runtime_ready} />
      <MetricCard label={t('copy.services_5cbd5840')} value={summary.background_services_ready} />
      <MetricCard label={t('copy.reference_tenant_a04947d9')} value={summary.reference_tenant_ready} />
      <MetricCard label={t('copy.readiness_score_041f08db')} value={readiness.readiness_score} />
      <MetricCard label={t('copy.postgresql_source_33bab8bf')} value={summary.postgresql_source_of_truth} />
    </section>
  );
}

function SchedulerWorkerSections({ runtime }: { runtime: SchedulerBackgroundServicesRuntime }) {
  const { t, date } = useI18n();
  return (
    <section className="table-card" data-scheduler-center-section="workers">
      <h2><LocalizedText id="copy.scheduler_and_worker_inventory_84087219" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.jobs_437736fd')} value={runtime.scheduler_summary.job_count} />
        <MetricCard label={t('copy.schedules_26d9d089')} value={runtime.scheduler_summary.schedule_count} />
        <MetricCard label={t('copy.recent_runs_af7051db')} value={runtime.scheduler_summary.scheduler_run_count_sample} />
        <MetricCard label={t('copy.workers_b6ef3acd')} value={runtime.worker_health.total_workers} />
        <MetricCard label={t('copy.ready_workers_cdfd3102')} value={runtime.worker_health.ready_workers} />
        <MetricCard label={t('copy.failed_workers_287fd91f')} value={runtime.worker_health.failed_workers} />
      </div>
      <table>
        <thead>
          <tr><th><LocalizedText id="copy.worker_99edd8c8" /></th><th><LocalizedText id="common.type" /></th><th><LocalizedText id="copy.desired_a382870d" /></th><th><LocalizedText id="copy.observed_2e159b44" /></th><th><LocalizedText id="copy.accepting_857beb3d" /></th><th><LocalizedText id="copy.heartbeat_eb4d4196" /></th></tr>
        </thead>
        <tbody>
          {runtime.worker_inventory.slice(0, 15).map((worker) => (
            <tr key={asText(worker.worker_id)}>
              <td>{asText(worker.worker_key)}</td>
              <td>{localizedProductLabel(worker.worker_type, t)}</td>
              <td>{localizedProductLabel(worker.desired_state, t)}</td>
              <td>{localizedProductLabel(worker.observed_state, t)}</td>
              <td>{localizedProductLabel(worker.accepting_work, t)}</td>
              <td>{worker.heartbeat_at ? date(String(worker.heartbeat_at), { dateStyle: 'medium', timeStyle: 'short' }) : t('common.notAvailable')}</td>
            </tr>
          ))}
          {runtime.worker_inventory.length === 0 ? <tr><td className="table-empty" colSpan={6}><LocalizedText id="common.noItems" /></td></tr> : null}
        </tbody>
      </table>
    </section>
  );
}

function RuntimeSections({ runtime }: { runtime: SchedulerBackgroundServicesRuntime }) {
  const { t } = useI18n();
  const lease = runtime.lease_management ?? {};
  const retry = runtime.retry_engine ?? {};
  const executions = runtime.runtime_executions ?? {};
  return (
    <section className="table-card" data-scheduler-center-section="runtime">
      <h2><LocalizedText id="copy.runtime_executions_leases_and_retries_adb57908" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.running_jobs_f1d16117')} value={executions.running_jobs} />
        <MetricCard label={t('copy.completed_jobs_18270228')} value={executions.completed_jobs} />
        <MetricCard label={t('copy.failed_jobs_ca3a7a0f')} value={executions.failed_jobs} />
        <MetricCard label={t('copy.pending_jobs_28ca9470')} value={executions.pending_jobs} />
        <MetricCard label={t('copy.active_leases_8d84fb02')} value={lease.active_attempts} />
        <MetricCard label={t('copy.expired_leases_d1daba1d')} value={lease.expired_leases} />
        <MetricCard label={t('copy.retry_candidates_4ac084c0')} value={retry.retry_candidates} />
        <MetricCard label={t('copy.retries_executed_b3dabb38')} value={retry.retry_executed_by_center} />
      </div>
    </section>
  );
}

function PipelineSections({ runtime }: { runtime: SchedulerBackgroundServicesRuntime }) {
  const { t } = useI18n();
  return (
    <section className="table-card" data-scheduler-center-section="pipelines">
      <h2><LocalizedText id="copy.background_pipelines_8361921e" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.pipelines_c5df1e14')} value={runtime.pipeline_health.pipeline_count} />
        <MetricCard label={t('copy.ready_pipelines_97ac5e0c')} value={runtime.pipeline_health.ready_pipelines} />
        <MetricCard label={t('copy.degraded_pipelines_71ff0477')} value={runtime.pipeline_health.degraded_pipelines} />
        <MetricCard label={t('copy.pipeline_health_18f4da59')} value={runtime.pipeline_health.pipeline_health} />
      </div>
      <table>
        <thead>
          <tr>
            <th><LocalizedText id="copy.service_329cb8b6" /></th>
            <th><LocalizedText id="copy.domain_9b10914d" /></th>
            <th><LocalizedText id="common.status" /></th>
            <th><LocalizedText id="copy.workflow_d7a48414" /></th>
            <th><LocalizedText id="copy.worker_required_8b9a3ab5" /></th>
            <th><LocalizedText id="copy.evidence_7ea014de" /></th>
          </tr>
        </thead>
        <tbody>
          {runtime.background_services.map((service) => {
            const evidence = asRecord(service.runtime_evidence);
            return (
              <tr key={asText(service.service_key)}>
                <td>{asText(service.service_name)}</td>
                <td>{asText(service.domain)}</td>
                <td>{asText(service.status)}</td>
                <td>{asText(service.workflow_status)}</td>
                <td>{asText(service.worker_execution_required)}</td>
                <td>{asText(evidence.count, '0')}<br /><small>{asText(evidence.source)}</small></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

function Diagnostics({ runtime }: { runtime: SchedulerBackgroundServicesRuntime }) {
  const { t } = useI18n();
  const diagnostics = runtime.operational_diagnostics ?? {};
  const groups = [
    ['Runtime bottlenecks', asList(diagnostics.runtime_bottlenecks)],
    ['Warnings', runtime.warnings],
    ['Pending capabilities', runtime.pending_capabilities],
    ['Recommendations', runtime.runtime_recommendations],
  ];
  return (
    <section className="table-card" data-scheduler-center-section="diagnostics">
      <h2><LocalizedText id="copy.operational_diagnostics_a65ef889" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.retry_opportunities_3fcc6527')} value={diagnostics.retry_opportunities} />
        <MetricCard label={t('copy.worker_inactivity_2067a3a3')} value={diagnostics.worker_inactivity} />
        <MetricCard label={t('copy.lease_anomalies_e6459a39')} value={diagnostics.lease_anomalies} />
        <MetricCard label={t('copy.reference_readiness_d1cd0816')} value={asRecord(runtime.reference_tenant).reference_tenant_ready} />
        <MetricCard label={t('copy.side_effects_f9b9f592')} value={runtime.side_effects_performed} />
        <MetricCard label={t('copy.external_calls_2326bb0c')} value={runtime.external_calls_performed} />
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

export function SchedulerBackgroundServicesCenter() {
  const { t } = useI18n();
  const [runtime, setRuntime] = useState<SchedulerBackgroundServicesRuntime | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const payload = await getSchedulerBackgroundServicesRuntime();
        if (!cancelled) setRuntime(payload);
      } catch (loadError) {
        if (!cancelled) {
          setError(
            loadError instanceof Error
              ? loadError.message
              : t('feedback.schedulerBackgroundServicesUnavailable'),
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
  }, [t]);

  if (loading) {
    return (
      <section className="card" data-scheduler-center-section="loading">
        <h2><LocalizedText id="copy.loading_background_services_ef13b381" /></h2>
        <p><LocalizedText id="copy.retrieving_scheduler_worker_runtime_and_pipeline_sta_989ee08e" /></p>
      </section>
    );
  }

  if (error || !runtime) {
    return (
      <section className="card" data-scheduler-center-section="error">
        <h2><LocalizedText id="copy.scheduler_center_unavailable_e4887066" /></h2>
        <p>{error ?? <LocalizedText id="copy.no_scheduler_background_services_runtime_payload_was_32b8da8a" />}</p>
      </section>
    );
  }

  return (
    <div className="stack">
      <Summary runtime={runtime} />
      <SchedulerWorkerSections runtime={runtime} />
      <RuntimeSections runtime={runtime} />
      <PipelineSections runtime={runtime} />
      <Diagnostics runtime={runtime} />
    </div>
  );
}
