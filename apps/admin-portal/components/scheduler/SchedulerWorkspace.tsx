'use client';

import { useI18n } from '../../i18n/I18nProvider';

import { LocalizedText } from '../layout/LocalizedText';

import { useCallback, useEffect, useState } from 'react';
import { useOrganization } from '../organization/OrganizationContext';
import { schedulerApi, type SchedulerJob, type SchedulerRun, type SchedulerSchedule } from '../../lib/scheduler-api';

const isoOrNull = (value: string) => value ? new Date(value).toISOString() : null;

export function SchedulerWorkspace({ canAdminister }: { canAdminister: boolean }) {
  const { t, date } = useI18n();
  const formatDate = (value?: string | null) => date(value, { dateStyle: 'medium', timeStyle: 'short' });
  const { organization, loading: organizationLoading, error: organizationError } = useOrganization();
  const [jobs, setJobs] = useState<SchedulerJob[]>([]);
  const [schedules, setSchedules] = useState<SchedulerSchedule[]>([]);
  const [runs, setRuns] = useState<SchedulerRun[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(t('feedback.selectOrganization'));

  const [jobCode, setJobCode] = useState('');
  const [jobName, setJobName] = useState('');
  const [operationType, setOperationType] = useState('');
  const [concurrencyPolicy, setConcurrencyPolicy] = useState('forbid_overlap');
  const [misfirePolicy, setMisfirePolicy] = useState('run_once');
  const [maxConcurrentRuns, setMaxConcurrentRuns] = useState(1);
  const [maxRuntimeSeconds, setMaxRuntimeSeconds] = useState('');

  const [scheduleJobId, setScheduleJobId] = useState('');
  const [cronExpression, setCronExpression] = useState('0 * * * *');
  const [timezone, setTimezone] = useState('UTC');
  const [startAt, setStartAt] = useState('');
  const [endAt, setEndAt] = useState('');

  const load = useCallback(async () => {
    if (!organization) return;
    const [j, s, r] = await Promise.all([
      schedulerApi.listJobs(organization.id),
      schedulerApi.listSchedules(organization.id),
      schedulerApi.listRuns(organization.id),
    ]);
    setJobs(j); setSchedules(s); setRuns(r);
    if (!scheduleJobId && j.length > 0) setScheduleJobId(j[0].id);
    setMessage(`Scheduler state loaded for ${organization.name}.`);
  }, [organization, scheduleJobId]);

  useEffect(() => {
    if (organizationLoading) { setMessage(t('feedback.organizationsLoading')); return; }
    if (organizationError) { setMessage(organizationError); return; }
    if (!organization) { setMessage(t('feedback.selectOrganization')); return; }
    setBusy(true);
    void load().catch((e) => setMessage(e instanceof Error ? e.message : t('feedback.loadFailed'))).finally(() => setBusy(false));
  }, [load, organization, organizationError, organizationLoading, t]);

  const act = async (action: () => Promise<unknown>, success: string) => {
    setBusy(true);
    try { await action(); await load(); setMessage(success); }
    catch (e) { setMessage(e instanceof Error ? e.message : t('feedback.actionFailed')); }
    finally { setBusy(false); }
  };

  const createJob = async () => {
    if (!organization) return;
    await act(() => schedulerApi.createJob(organization.id, {
      code: jobCode.trim(),
      name: jobName.trim(),
      description: null,
      operation_type: operationType.trim(),
      parameters: {},
      enabled: false,
      concurrency_policy: concurrencyPolicy,
      misfire_policy: misfirePolicy,
      max_concurrent_runs: maxConcurrentRuns,
      max_runtime_seconds: maxRuntimeSeconds ? Number(maxRuntimeSeconds) : null,
    }), 'Operational job created in disabled state.');
    setJobCode(''); setJobName(''); setOperationType(''); setMaxRuntimeSeconds('');
  };

  const createSchedule = async () => {
    if (!organization) return;
    await act(() => schedulerApi.createSchedule(organization.id, {
      operational_job_id: scheduleJobId,
      schedule_expression: cronExpression.trim(),
      timezone: timezone.trim(),
      enabled: false,
      start_at: isoOrNull(startAt),
      end_at: isoOrNull(endAt),
    }), 'Schedule created in disabled state.');
    setStartAt(''); setEndAt('');
  };

  const unavailable = busy || !organization || Boolean(organizationError);

  return <div className="builder-content">
    {canAdminister ? <section className="card">
      <h2><LocalizedText id="copy.create_operational_job_2cd86858" /></h2>
      <label className="field-label"><LocalizedText id="common.code" /></label><input className="field-control" value={jobCode} onChange={(e) => setJobCode(e.target.value)} />
      <label className="field-label"><LocalizedText id="common.name" /></label><input className="field-control" value={jobName} onChange={(e) => setJobName(e.target.value)} />
      <label className="field-label"><LocalizedText id="copy.operation_type_dbcc43cc" /></label><input className="field-control" value={operationType} onChange={(e) => setOperationType(e.target.value)} placeholder={t('copy.platform_operation_13a7d443')} />
      <label className="field-label"><LocalizedText id="copy.concurrency_policy_c55815dd" /></label><select className="field-control" value={concurrencyPolicy} onChange={(e) => setConcurrencyPolicy(e.target.value)}><option value="forbid_overlap"><LocalizedText id="copy.forbid_overlap_6507cb8f" /></option><option value="allow_bounded"><LocalizedText id="copy.allow_bounded_218400b1" /></option><option value="replace_pending"><LocalizedText id="copy.replace_pending_430ac6df" /></option></select>
      <label className="field-label"><LocalizedText id="copy.misfire_policy_909f862b" /></label><select className="field-control" value={misfirePolicy} onChange={(e) => setMisfirePolicy(e.target.value)}><option value="skip"><LocalizedText id="copy.skip_c7e16815" /></option><option value="run_once"><LocalizedText id="copy.run_once_f8ed5ce7" /></option><option value="catch_up_bounded"><LocalizedText id="copy.catch_up_bounded_ab9ade87" /></option></select>
      <label className="field-label"><LocalizedText id="copy.max_concurrent_runs_0a3f9f62" /></label><input className="field-control" type="number" min={1} value={maxConcurrentRuns} onChange={(e) => setMaxConcurrentRuns(Math.max(1, Number(e.target.value) || 1))} />
      <label className="field-label"><LocalizedText id="copy.max_runtime_seconds_ab611c3b" /></label><input className="field-control" type="number" min={1} value={maxRuntimeSeconds} onChange={(e) => setMaxRuntimeSeconds(e.target.value)} />
      <button className="button" disabled={unavailable || !jobCode.trim() || !jobName.trim() || !operationType.trim()} onClick={() => void createJob()}><LocalizedText id="copy.create_job_b9a73844" /></button>
    </section> : null}

    {canAdminister ? <section className="card">
      <h2><LocalizedText id="copy.create_schedule_17178120" /></h2>
      <label className="field-label"><LocalizedText id="copy.operational_job_821e8047" /></label><select className="field-control" value={scheduleJobId} onChange={(e) => setScheduleJobId(e.target.value)}><option value=""><LocalizedText id="copy.select_a_job_90a05756" /></option>{jobs.map((job) => <option key={job.id} value={job.id}>{job.name}</option>)}</select>
      <label className="field-label"><LocalizedText id="copy.cron_expression_0a2e9455" /></label><input className="field-control" value={cronExpression} onChange={(e) => setCronExpression(e.target.value)} />
      <label className="field-label"><LocalizedText id="copy.timezone_d1f7dc89" /></label><input className="field-control" value={timezone} onChange={(e) => setTimezone(e.target.value)} />
      <label className="field-label"><LocalizedText id="copy.start_at_240e1ac6" /></label><input className="field-control" type="datetime-local" value={startAt} onChange={(e) => setStartAt(e.target.value)} />
      <label className="field-label"><LocalizedText id="copy.end_at_25c141a5" /></label><input className="field-control" type="datetime-local" value={endAt} onChange={(e) => setEndAt(e.target.value)} />
      <button className="button" disabled={unavailable || !scheduleJobId || !cronExpression.trim() || !timezone.trim()} onClick={() => void createSchedule()}><LocalizedText id="copy.create_schedule_cf797357" /></button>
    </section> : null}

    <section className="card">
      <h2><LocalizedText id="copy.scheduler_administration_09558682" /></h2>
      <p><LocalizedText id="copy.create_jobs_in_a_disabled_state_attach_schedules_the_217b9481" /></p>
      {canAdminister ? <button className="button" disabled={unavailable} onClick={() => organization && void act(() => schedulerApi.evaluate(organization.id), 'Evaluation completed.')}><LocalizedText id="copy.evaluate_now_ab3fbb56" /></button> : null}
      <button className="button secondary" disabled={unavailable} onClick={() => void load()}><LocalizedText id="common.actions.refresh" /></button>
      <small className="muted-text">{message}</small>
    </section>

    <section className="table-card"><h2><LocalizedText id="copy.operational_jobs_76acc7d4" /></h2><table><thead><tr><th><LocalizedText id="common.code" /></th><th><LocalizedText id="common.name" /></th><th><LocalizedText id="copy.operation_430d3207" /></th><th><LocalizedText id="copy.policies_8d611849" /></th><th><LocalizedText id="common.status" /></th>{canAdminister ? <th /> : null}</tr></thead><tbody>{jobs.map((job) => <tr key={job.id}><td>{job.code}</td><td>{job.name}</td><td>{job.operation_type}</td><td>{job.concurrency_policy} / {job.misfire_policy}</td><td>{job.enabled ? <LocalizedText id="copy.enabled_3ea3f980" /> : <LocalizedText id="copy.disabled_07596f18" />}</td>{canAdminister ? <td><button className="button secondary" disabled={unavailable} onClick={() => organization && void act(() => schedulerApi.updateJob(organization.id, job.id, { enabled: !job.enabled }), 'Job updated.')}>{job.enabled ? <LocalizedText id="copy.disable_9a7d4e06" /> : <LocalizedText id="copy.enable_20063ad9" />}</button><button className="button" disabled={unavailable || !job.enabled} onClick={() => organization && void act(() => schedulerApi.trigger(organization.id, job.id, `portal-${Date.now()}`), 'Run requested.')}><LocalizedText id="copy.run_now_2af00e23" /></button></td> : null}</tr>)}{jobs.length === 0 ? <tr><td colSpan={canAdminister ? 6 : 5}><LocalizedText id="copy.no_operational_jobs_are_configured_for_this_organiza_33e77a51" /></td></tr> : null}</tbody></table></section>

    <section className="table-card"><h2><LocalizedText id="copy.schedules_26d9d089" /></h2><table><thead><tr><th><LocalizedText id="copy.expression_97b695b9" /></th><th><LocalizedText id="copy.timezone_d1f7dc89" /></th><th><LocalizedText id="copy.window_41dfc0a6" /></th><th><LocalizedText id="copy.next_run_6c03cbdc" /></th><th><LocalizedText id="common.status" /></th>{canAdminister ? <th /> : null}</tr></thead><tbody>{schedules.map((schedule) => <tr key={schedule.id}><td>{schedule.schedule_expression}</td><td>{schedule.timezone}</td><td>{formatDate(schedule.start_at)} → {formatDate(schedule.end_at)}</td><td>{formatDate(schedule.next_run_at)}</td><td>{schedule.enabled ? <LocalizedText id="copy.enabled_3ea3f980" /> : <LocalizedText id="copy.disabled_07596f18" />}</td>{canAdminister ? <td><button className="button secondary" disabled={unavailable} onClick={() => organization && void act(() => schedulerApi.updateSchedule(organization.id, schedule.id, { enabled: !schedule.enabled }), 'Schedule updated.')}>{schedule.enabled ? <LocalizedText id="copy.disable_9a7d4e06" /> : <LocalizedText id="copy.enable_20063ad9" />}</button></td> : null}</tr>)}{schedules.length === 0 ? <tr><td colSpan={canAdminister ? 6 : 5}><LocalizedText id="copy.no_schedules_are_configured_for_this_organization_5820792c" /></td></tr> : null}</tbody></table></section>

    <section className="table-card"><h2><LocalizedText id="copy.recent_runs_37f4a7b7" /></h2><table><thead><tr><th><LocalizedText id="common.status" /></th><th><LocalizedText id="copy.trigger_d3f06a58" /></th><th><LocalizedText id="copy.requested_c26bf60f" /></th><th><LocalizedText id="copy.scheduled_1cd1bdad" /></th><th><LocalizedText id="copy.runtime_c4740e4c" /></th><th><LocalizedText id="copy.issue_73781a12" /></th></tr></thead><tbody>{runs.map((run) => <tr key={run.id}><td>{run.status}</td><td>{run.trigger_type}</td><td>{formatDate(run.requested_at)}</td><td>{formatDate(run.scheduled_for)}</td><td>{run.runtime_execution_id ?? '—'}</td><td>{run.error_code ?? <LocalizedText id="copy.no_issue_reported_0201f9cf" />}</td></tr>)}{runs.length === 0 ? <tr><td colSpan={6}><LocalizedText id="copy.no_scheduler_runs_have_been_recorded_for_this_organi_42b918d3" /></td></tr> : null}</tbody></table></section>
  </div>;
}
