'use client';

import { LocalizedText } from '../layout/LocalizedText';
import { useI18n } from '../../i18n/I18nProvider';

import { useCallback, useEffect, useState } from 'react';
import { runtimeWorkersApi, type RuntimeWorkerSummary } from '../../lib/runtime-workers-api';

export function WorkerSummaryCards() {
  const { t, date } = useI18n();
  const [summary, setSummary] = useState<RuntimeWorkerSummary | null>(null);
  const [message, setMessage] = useState(t('feedback.workerSummaryLoading'));

  const load = useCallback(async () => {
    try {
      const result = await runtimeWorkersApi.summary();
      setSummary(result);
      setMessage(t('dynamic.calculatedAt', { date: date(result.calculated_at, { dateStyle: 'medium', timeStyle: 'short' }) }));
    } catch (error) {
      setSummary(null);
      setMessage(error instanceof Error ? error.message : t('feedback.workerSummaryFailed'));
    }
  }, [date, t]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section className="card">
      <h2><LocalizedText id="copy.worker_capacity_summary_97556e14" /></h2>
      {summary ? (
        <div className="grid">
          <article><strong><LocalizedText id="copy.total_b25928c6" /></strong><p>{summary.total_workers}</p></article>
          <article><strong><LocalizedText id="status.ready" /></strong><p>{summary.ready_workers}</p></article>
          <article><strong><LocalizedText id="copy.accepting_work_864a38da" /></strong><p>{summary.accepting_work}</p></article>
          <article><strong><LocalizedText id="copy.stale_189cc40c" /></strong><p>{summary.stale_workers}</p></article>
          <article><strong><LocalizedText id="copy.degraded_13c27ff8" /></strong><p>{summary.degraded_workers}</p></article>
          <article><strong><LocalizedText id="copy.capacity_45bd908d" /></strong><p>{Math.round(summary.available_capacity_ratio * 100)}%</p></article>
        </div>
      ) : <p><LocalizedText id="copy.no_worker_summary_is_available_abfdd8f0" /></p>}
      <button className="button secondary" type="button" onClick={() => void load()}>
        <LocalizedText id="copy.refresh_worker_summary_558fa287" /></button>
      <small className="muted-text">{message}</small>
    </section>
  );
}
