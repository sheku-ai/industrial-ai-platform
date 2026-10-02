import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = process.cwd();
const api = readFileSync(resolve(root, 'lib/operations-api.ts'), 'utf8');
const panel = readFileSync(resolve(root, 'components/operations/OperationalHealthIssues.tsx'), 'utf8');
const workspace = readFileSync(resolve(root, 'components/operations/OperationsWorkspace.tsx'), 'utf8');

const checks = {
  issue_type: api.includes('OperationalHealthIssue'),
  issues_field: api.includes('issues: OperationalHealthIssue[]'),
  severity_visible: panel.includes('issue.severity'),
  code_visible: panel.includes('issue.code'),
  resource_visible: panel.includes('issue.resource_key'),
  detail_visible: panel.includes('issue.message'),
  workspace_integration: workspace.includes('<OperationalHealthIssues issues={health.issues ?? []} />'),
};

const result = { ...checks, passed: Object.values(checks).every(Boolean) };
console.log(JSON.stringify(result, null, 2));
process.exit(result.passed ? 0 : 1);
