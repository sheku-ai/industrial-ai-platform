import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = process.cwd();
const api = readFileSync(resolve(root, 'lib/operations-api.ts'), 'utf8');
const workspace = readFileSync(
  resolve(root, 'components/operations/OperationsWorkspace.tsx'),
  'utf8',
);
const platformWorkers = readFileSync(
  resolve(root, 'components/operations/PlatformWorkerOperations.tsx'),
  'utf8',
);
const surface = readFileSync(
  resolve(root, 'components/operations/OperationsSurface.tsx'),
  'utf8',
);

const checks = {
  organization_health_header: api.includes("'X-Organization-ID': organizationId"),
  worker_control_plane_field_absent: !api.includes('worker_control_plane'),
  scheduler_worker_fields_absent: !api.includes('latest_worker_status'),
  organization_status_label:
    workspace.includes('<LocalizedText id="copy.organization_operational_status_8b02c05c" />'),
  scheduler_worker_panel_absent: !workspace.includes('<h2>Scheduler Worker</h2>'),
  platform_worker_section_present:
    platformWorkers.includes('<LocalizedText id="copy.platform_worker_operations_d5235db4" />')
    && surface.includes("import { PlatformWorkerOperations } from './PlatformWorkerOperations'")
    && surface.includes('<PlatformWorkerOperations />')
    && !workspace.includes('PlatformWorkerOperations'),
};

const result = { ...checks, passed: Object.values(checks).every(Boolean) };
console.log(JSON.stringify(result, null, 2));
process.exit(result.passed ? 0 : 1);
