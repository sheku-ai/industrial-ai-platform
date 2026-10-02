import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = process.cwd();
const api = readFileSync(resolve(root, 'lib/runtime-workers-api.ts'), 'utf8');
const summary = readFileSync(resolve(root, 'components/operations/WorkerSummaryCards.tsx'), 'utf8');
const section = readFileSync(resolve(root, 'components/operations/PlatformWorkerOperations.tsx'), 'utf8');

const checks = {
  summary_endpoint: api.includes('/api/control-plane/workers/summary'),
  summary_type: api.includes('RuntimeWorkerSummary'),
  platform_scope_header: api.includes("'X-Authorization-Scope': 'platform'"),
  organization_parameter_absent: !api.includes('organizationId'),
  capacity_ratio: summary.includes('available_capacity_ratio'),
  stale_workers: summary.includes('stale_workers'),
  degraded_workers: summary.includes('degraded_workers'),
  accepting_work: summary.includes('accepting_work'),
  platform_binding: section.includes('<WorkerSummaryCards />'),
};

const result = { ...checks, passed: Object.values(checks).every(Boolean) };
console.log(JSON.stringify(result, null, 2));
process.exit(result.passed ? 0 : 1);
