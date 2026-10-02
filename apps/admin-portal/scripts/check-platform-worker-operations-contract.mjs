import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const apiClient = fs.readFileSync(path.join(root, 'lib/runtime-workers-api.ts'), 'utf8');
const page = fs.readFileSync(path.join(root, 'app/operations/page.tsx'), 'utf8');
const surface = fs.readFileSync(
  path.join(root, 'components/operations/OperationsSurface.tsx'),
  'utf8',
);
const section = fs.readFileSync(
  path.join(root, 'components/operations/PlatformWorkerOperations.tsx'),
  'utf8',
);
const control = fs.readFileSync(
  path.join(root, 'components/operations/WorkerControlPanel.tsx'),
  'utf8',
);
const summary = fs.readFileSync(
  path.join(root, 'components/operations/WorkerSummaryCards.tsx'),
  'utf8',
);

const checks = {
  platform_scope_header: apiClient.includes("'X-Authorization-Scope': 'platform'"),
  organization_header_absent: !apiClient.includes("'X-Organization-ID'"),
  api_client_has_no_organization_parameter: !apiClient.includes('organizationId'),
  page_uses_platform_section:
    page.includes('OperationsSurface')
    && surface.includes("import { PlatformWorkerOperations } from './PlatformWorkerOperations'")
    && surface.includes('actionAvailable ?')
    && surface.includes('<PlatformWorkerOperations />'),
  section_renders_summary: section.includes('<WorkerSummaryCards />'),
  section_renders_controls: section.includes('<WorkerControlPanel />'),
  control_has_no_organization_parameter: !control.includes('organizationId'),
  summary_has_no_organization_parameter: !summary.includes('organizationId'),
};

const result = { ...checks, passed: Object.values(checks).every(Boolean) };
console.log(JSON.stringify(result, null, 2));
process.exit(result.passed ? 0 : 1);
