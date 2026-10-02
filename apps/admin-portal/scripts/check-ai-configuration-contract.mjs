import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = process.cwd();
const read = (path) => readFileSync(resolve(root, path), 'utf8');

const api = read('lib/model-provider-center-api.ts');
const workspace = read('components/models/ModelProviderCenterWorkspace.tsx');
const navigationApi = read('lib/platform-dashboard-api.ts');
const sidebar = read('components/layout/Sidebar.tsx');
const destination = read('components/ai/AIConfigurationDestination.tsx');
const organizationContext = read('components/organization/OrganizationContext.tsx');

const checks = {
  organization_workspace: api.includes("'/api/ai/configuration'"),
  provider_mutations:
  [
    '/api/ai/providers',
    '/enabled',
    '/validate',
  ].every((contract) => api.includes(contract))
  && api.includes('setProviderArchived')
  && api.includes("${archived ? 'archive' : 'restore'}"),
  model_mutations:
    [
      '/api/ai/models',
      '/default',
      '/enabled',
      '/validate',
    ].every((contract) => api.includes(contract))
    && api.includes('setModelArchived')
    && api.includes("${archived ? 'archive' : 'restore'}"),
  read_only_hides_provider_form:
    workspace.includes('!providerAdmin ?') && workspace.includes('<ProviderForm'),
  read_only_hides_model_form:
    workspace.includes('!modelAdmin ?') && workspace.includes('<ModelForm'),
  empty_states:
    workspace.includes("t('aiConfig.noProviders')") && workspace.includes("t('aiConfig.noModels')"),
  error_and_retry:
    workspace.includes('role="alert"') && workspace.includes("t('common.actions.retry')"),
  credential_value_not_rendered:
    !workspace.includes('credential_reference') && workspace.includes('credential_configured'),
  backend_availability:
    workspace.includes('provider.availability_status')
    && workspace.includes('model.availability_status')
    && !workspace.includes('provider.enabled ? true'),
  stale_evidence: workspace.includes("evidence.evidence_status === 'stale'"),
  disabled_model_crud:
    workspace.includes('modelCapabilities={runtime.model_capabilities}')
    && workspace.includes("provider.lifecycle_status === 'active'")
    && !workspace.includes('provider.available ? <ModelForm'),
  runtime_actions_blocked:
    workspace.includes('model.runtime_actions.enable.allowed')
    && workspace.includes('model.runtime_actions.validate.allowed')
    && workspace.includes('model.runtime_actions.set_default.allowed'),
  authoritative_runtime_reason:
    workspace.includes('model.runtime_actions.enable.reason')
    && api.includes('availability_reason'),
  configuration_only_notice:
    workspace.includes(
      'const runtimeHasExecutableAdapters = runtime.adapters.some((adapter) => adapter.execution_supported)',
    )
    && workspace.includes(
      'const runtimeHasConfigurationAdapter = runtime.adapters.some((adapter) => adapter.configuration_supported)',
    )
    && workspace.includes('{!runtimeHasExecutableAdapters ? (')
    && workspace.includes(
      "t(runtimeHasConfigurationAdapter ? 'aiConfig.noExecutableAdapters' : 'aiConfig.noAdapterContractHelp')",
    ),
  mutations_blocked: workspace.includes('disabled={pending'),
  status_specific_errors:
    read('lib/platform-api.ts').includes('status === 403')
    && read('lib/platform-api.ts').includes('status === 409'),
  authorization_navigation:
    navigationApi.includes('ai_configuration:')
    && sidebar.includes("productCapability: 'ai_configuration'")
    && destination.includes('navigationCapabilities?.ai_configuration?.visible')
    && organizationContext.includes('Promise.allSettled')
    && workspace.includes('errorStatus === 403'),
  forbidden_has_no_retry:
    workspace.indexOf('errorStatus === 403')
      < workspace.indexOf("t('common.actions.retry')"),
  adapter_catalog_from_backend:
    workspace.includes('adapters.map') && !workspace.includes("['openai'"),
};

const result = { ...checks, passed: Object.values(checks).every(Boolean) };
console.log(JSON.stringify(result, null, 2));
process.exit(result.passed ? 0 : 1);
