import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = process.cwd();
const read = (path) => readFileSync(resolve(root, path), 'utf8');

const api = read('lib/runtime-workers-api.ts');
const platformApi = read('lib/platform-api.ts');
const panel = read('components/operations/WorkerControlPanel.tsx');
const section = read('components/operations/PlatformWorkerOperations.tsx');
const surface = read('components/operations/OperationsSurface.tsx');
const page = read('app/operations/page.tsx');
const backendRoute = read('../api/app/api/routes/runtime_workers.py');

const checks = {
  list_endpoint: api.includes("'/api/control-plane/workers'"),
  desired_state_endpoint: api.includes('/desired-state'),
  desired_state_put:
    api.includes('platformApi.put<RuntimeWorker>')
    && platformApi.includes("put: <T>")
    && platformApi.includes("method: 'PUT'"),
  history_endpoint: api.includes('/history?limit=20'),
  platform_scope_header: api.includes("'X-Authorization-Scope': 'platform'"),
  organization_header_absent: !api.includes("'X-Organization-ID'"),
  actor_header:
    !api.includes("'X-Actor-Reference'")
    && backendRoute.includes('actor_id=context.actor_reference')
    && backendRoute.includes('_require(context, "administer")'),
  bounded_states: panel.includes("['active', 'paused', 'draining', 'disabled']"),
  confirmation_required: panel.includes('window.confirm'),
  readiness_visible: panel.includes('worker.ready'),
  stale_visible: panel.includes('worker.heartbeat_stale'),
  history_visible:
    panel.includes('copy.worker_history_c3d12bbe')
    && panel.includes('history.map')
    && panel.includes('item.actor_id ?? item.actor_type')
    && panel.includes('item.before_state')
    && panel.includes('item.after_state'),
  platform_section: section.includes('<WorkerControlPanel />'),
  operations_integration:
    page.includes('<OperationsSurface />')
    && surface.includes("import { PlatformWorkerOperations } from './PlatformWorkerOperations'")
    && surface.includes('actionAvailable ?')
    && surface.includes('<PlatformWorkerOperations />'),
};

const result = { ...checks, passed: Object.values(checks).every(Boolean) };
console.log(JSON.stringify(result, null, 2));
process.exit(result.passed ? 0 : 1);
