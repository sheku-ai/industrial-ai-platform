'use client';

import { LocalizedText } from '../layout/LocalizedText';

import { WorkerControlPanel } from './WorkerControlPanel';
import { WorkerSummaryCards } from './WorkerSummaryCards';

export function PlatformWorkerOperations() {
  return (
    <section aria-labelledby="platform-worker-operations-title">
      <header className="header">
        <h2 id="platform-worker-operations-title"><LocalizedText id="copy.platform_worker_operations_d5235db4" /></h2>
        <p><LocalizedText id="copy.inspect_global_runtime_capacity_and_administer_platf_65d21ae4" /></p>
      </header>
      <WorkerSummaryCards />
      <WorkerControlPanel />
    </section>
  );
}
