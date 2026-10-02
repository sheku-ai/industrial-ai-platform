'use client';

import { LocalizedText } from '../layout/LocalizedText';
import { useI18n } from '../../i18n/I18nProvider';

import { useCallback, useEffect, useState } from 'react';

import {
  runtimeWorkersApi,
  type RuntimeWorker,
  type RuntimeWorkerHistory,
  type WorkerDesiredState,
} from '../../lib/runtime-workers-api';
import { localizedProductLabel, productStatus } from '../../lib/presentation';

function stateSummary(value: Record<string, unknown> | null | undefined, fallback: string): string {
  if (!value || Object.keys(value).length === 0) return fallback;
  return Object.entries(value)
    .filter(([, item]) => item !== null && item !== undefined && typeof item !== 'object')
    .map(([key, item]) => `${key.replaceAll('_', ' ')}: ${String(item)}`)
    .join('; ') || fallback;
}

export function WorkerControlPanel() {
  const { t, date } = useI18n();
  const formatDate = (value?: string | null) => date(value, { dateStyle: 'medium', timeStyle: 'short' });
  const [workers, setWorkers] = useState<RuntimeWorker[]>([]);
  const [history, setHistory] = useState<RuntimeWorkerHistory[]>([]);
  const [selectedWorker, setSelectedWorker] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState(t('feedback.workersLoading'));

  const loadWorkers = useCallback(async () => {
    setLoading(true);
    try {
      const result = await runtimeWorkersApi.list();
      setWorkers(result);
      setMessage(`${t('copy.worker_99edd8c8')}: ${result.length}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t('feedback.workersLoadFailed'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadWorkers();
  }, [loadWorkers]);

  const changeState = async (worker: RuntimeWorker, desiredState: WorkerDesiredState) => {
    const confirmed = window.confirm(
      t('dynamic.confirmWorkerStateChange', { worker: worker.worker_key, current: worker.desired_state, next: desiredState }),
    );
    if (!confirmed) return;

    setLoading(true);
    try {
      const updated = await runtimeWorkersApi.setDesiredState(worker.worker_key, desiredState);
      setWorkers((current) => current.map((item) => (
        item.worker_key === updated.worker_key ? updated : item
      )));
      setMessage(`${worker.worker_key}: ${t('common.updated')}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t('feedback.workerCommandFailed'));
    } finally {
      setLoading(false);
    }
  };

  const loadHistory = async (workerKey: string) => {
    setSelectedWorker(workerKey);
    setLoading(true);
    try {
      setHistory(await runtimeWorkersApi.history(workerKey));
    } catch (error) {
      setHistory([]);
      setMessage(error instanceof Error ? error.message : t('feedback.workerHistoryFailed'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <section className="table-card">
        <h2><LocalizedText id="copy.platform_worker_control_plane_e5ea3d59" /></h2>
        <p className="muted-text"><LocalizedText id="copy.global_worker_state_readiness_and_bounded_lifecycle__d7e96242" /></p>
        <button className="button secondary" type="button" disabled={loading} onClick={() => void loadWorkers()}>
          <LocalizedText id="copy.refresh_workers_d4d80639" /></button>
        <small className="muted-text">{message}</small>
        <table>
          <thead>
            <tr>
              <th><LocalizedText id="copy.worker_99edd8c8" /></th><th><LocalizedText id="common.type" /></th><th><LocalizedText id="copy.desired_a382870d" /></th><th><LocalizedText id="copy.observed_2e159b44" /></th><th><LocalizedText id="status.ready" /></th><th><LocalizedText id="copy.heartbeat_eb4d4196" /></th><th><LocalizedText id="common.actionColumn" /></th>
            </tr>
          </thead>
          <tbody>
            {workers.map((worker) => (
              <tr key={worker.worker_key}>
                <td><strong>{worker.worker_key}</strong></td>
                <td>{localizedProductLabel(worker.worker_type, t)}</td>
                <td><span className={`product-status product-status-${productStatus(worker.desired_state)}`}>{localizedProductLabel(worker.desired_state, t)}</span></td>
                <td>{localizedProductLabel(worker.observed_state, t)}{worker.heartbeat_stale ? <> · <LocalizedText id="copy.stale_e3a3a52f" /></> : null}</td>
                <td>{localizedProductLabel(worker.ready, t)}</td>
                <td>{formatDate(worker.heartbeat_at)}</td>
                <td>
                  <label className="sr-only" htmlFor={`worker-state-${worker.worker_key}`}><LocalizedText id="copy.desired_a382870d" /></label>
                  <select className="field-control" disabled={loading} id={`worker-state-${worker.worker_key}`} onChange={(event) => void changeState(worker, event.target.value as WorkerDesiredState)} value={worker.desired_state}>
                    {(['active', 'paused', 'draining', 'disabled'] as WorkerDesiredState[]).map((state) => <option key={state} value={state}>{localizedProductLabel(state, t)}</option>)}
                  </select>
                  <button className="button secondary" type="button" disabled={loading} onClick={() => void loadHistory(worker.worker_key)}>
                    <LocalizedText id="copy.history_66f79d8a" /></button>
                </td>
              </tr>
            ))}
            {workers.length === 0 ? <tr><td colSpan={7}><LocalizedText id="copy.no_platform_workers_are_registered_1ceb48c2" /></td></tr> : null}
          </tbody>
        </table>
      </section>

      {selectedWorker && (
        <section className="table-card">
          <h2><LocalizedText id="copy.worker_history_c3d12bbe" />{selectedWorker}</h2>
          <table>
            <thead><tr><th><LocalizedText id="copy.time_6c82e6dd" /></th><th><LocalizedText id="copy.action_97c89a4d" /></th><th><LocalizedText id="copy.actor_cbd19b5c" /></th><th><LocalizedText id="copy.before_74f39697" /></th><th><LocalizedText id="copy.after_79ba5e1b" /></th></tr></thead>
            <tbody>
              {history.map((item) => (
                <tr key={item.id}>
                  <td>{formatDate(item.created_at)}</td>
                  <td>{item.action}</td>
                  <td>{item.actor_id ?? item.actor_type ?? <LocalizedText id="copy.system_317f1e76" />}</td>
                  <td><small>{stateSummary(item.before_state, t('common.noItems'))}</small></td>
                  <td><small>{stateSummary(item.after_state, t('common.noItems'))}</small></td>
                </tr>
              ))}
              {history.length === 0 ? <tr><td colSpan={5}><LocalizedText id="copy.no_worker_history_is_available_for_this_worker_d1e89f41" /></td></tr> : null}
            </tbody>
          </table>
        </section>
      )}
    </>
  );
}
