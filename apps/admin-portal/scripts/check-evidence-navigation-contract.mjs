import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = process.cwd();
const read = (path) => readFileSync(resolve(root, path), 'utf8');

const reporting = read('components/analytics/ReportingAnalyticsCenter.tsx');
const governance = read('components/governance/GovernanceCenter.tsx');
const operationsPage = read('app/operations/page.tsx');
const operationsSurface = read('components/operations/OperationsSurface.tsx');
const operationsCenter = read('components/operations/OperationsCenter.tsx');
const contextContract = read('lib/operations-evidence-context.ts');
const capabilityState = read('components/layout/PlatformCapabilityState.tsx');
const organizationContext = read('components/organization/OrganizationContext.tsx');
const organizationScope = read('components/layout/OrganizationScope.tsx');
const operationsApi = read('lib/operations-center-api.ts');
const operationsRoute = read('../api/app/api/routes/operations_center.py');
const operationsSchema = read('../api/app/schemas/operations_center.py');
const operationalRoutes = read('../api/app/api/routes/operational_observability.py');
const apiPolicy = read('../api/app/security/api_policy.py');

const checks = {
  reporting_authorized_action:
    reporting.includes("operationsAccess === 'available'")
    && reporting.includes('href="/operations"'),
  reporting_restricted_information:
    reporting.includes('report-access-note')
    && reporting.includes("'navigation.platformPermissionRequired'"),
  governance_uses_backend_capability:
    governance.includes("platformCapabilityAvailable(navigationCapabilities, 'operations')")
    && governance.includes("operationsAccess !== 'available'"),
  governance_stable_context:
    governance.includes('buildOperationsEvidenceHref')
    && governance.includes('organizationId')
    && governance.includes('controlId: code')
    && governance.includes('domain: governanceDomain(item)')
    && governance.includes('status: String(item.status ?? fallbackStatus)'),
  durable_url_contract: [
    'evidence_organization',
    'evidence_control',
    'evidence_domain',
    'evidence_status',
  ].every((key) => contextContract.includes(key)),
  reload_parses_url:
    operationsSurface.includes('useSearchParams()')
    && operationsSurface.includes('parseOperationsEvidenceContext(searchParameters)')
    && operationsPage.includes('<Suspense'),
  context_can_be_cleared:
    operationsSurface.includes('href="/operations"')
    && operationsSurface.includes("t('common.actions.close')"),
  organization_change_invalidates_context:
    operationsSurface.includes('organization?.id === evidenceContext.organizationId')
    && operationsCenter.includes('authoritativeOrganizationId === context.organizationId'),
  contextual_empty_state:
    operationsCenter.includes('relatedRecords.length === 0')
    && operationsCenter.includes('common.noItems'),
  related_evidence_is_selected:
    operationsCenter.includes('data-operations-center-section="contextual-evidence"')
    && operationsCenter.includes('data-evidence-related="true"'),
  no_parameters_preserve_general_view:
    operationsSurface.includes('hasOperationsEvidenceParameters(searchParameters)')
    && operationsSurface.includes('hasEvidenceParameters ?'),
  route_remains_protected:
    operationsSurface.includes('<PlatformCapabilityState capability="operations">')
    && capabilityState.includes("data-platform-capability-state=\"restricted\"")
    && apiPolicy.includes('(\"/api/platform/operations\", _requirement(\"platform.operations\"))'),
  global_operations_resolve_without_organization:
    organizationContext.includes('if (!organization)')
    && organizationContext.includes('const operationsRuntime = await getOperationsCenterRuntime()')
    && organizationContext.includes("operationsRuntime.authorization['platform.operations:read']")
    && organizationContext.includes("operationsRuntime.authorization['platform.operations:administer']"),
  restricted_global_identity_resolves_denied:
    organizationContext.includes('cause instanceof PlatformApiError && cause.status === 403')
    && organizationContext.includes('setNavigationCapabilities(platformOperationsCapabilities(false, false))')
    && organizationContext.includes('setCapabilitiesResolved(true)'),
  operations_bypasses_only_organization_gate:
    organizationScope.includes("pathname === '/operations'")
    && organizationScope.includes("pathname.startsWith('/operations/')")
    && organizationScope.includes('return <div className="platform-scope">{children}</div>')
    && organizationScope.includes('if (!organization)'),
  operations_authorization_response_contract:
    operationsRoute.includes('context: RuntimeRequestContext = Depends(get_runtime_context)')
    && operationsRoute.includes('context.has_permission("platform.operations", "read")')
    && operationsRoute.includes('context.has_permission("platform.operations", "administer")')
    && operationsSchema.includes('alias="platform.operations:read"')
    && operationsSchema.includes('alias="platform.operations:administer"')
    && operationsApi.includes("'platform.operations:read': boolean")
    && operationsApi.includes("'platform.operations:administer': boolean"),
  administer_drives_global_scheduler_and_actions:
    organizationContext.includes('scheduler: { visible: administer, action_available: administer }')
    && organizationContext.includes('operations: { visible: read, action_available: administer }'),
  mutating_operations_remain_server_gated:
    operationalRoutes.includes('_require(context, "administer")')
    && apiPolicy.includes('(\"/api/platform/operations\", _requirement(\"platform.operations\"))'),
};

const result = { ...checks, passed: Object.values(checks).every(Boolean) };
console.log(JSON.stringify(result, null, 2));
process.exit(result.passed ? 0 : 1);
