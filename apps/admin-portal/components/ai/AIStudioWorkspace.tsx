'use client';

import { LocalizedText } from '../layout/LocalizedText';
import { useI18n } from '../../i18n/I18nProvider';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { getAIStudioRuntime, type AIStudioRuntime } from '../../lib/ai-studio-api';
import { localizedApiError, localizedProductLabel, productLabel } from '../../lib/presentation';
import { useOrganization } from '../organization/OrganizationContext';

function asText(value: unknown, fallback = '-'): string {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'boolean') return String(value);
  if (typeof value === 'string' && /^[a-z0-9]+(?:_[a-z0-9]+)+$/.test(value)) return productLabel(value, fallback);
  return String(value);
}

const AI_STUDIO_VALUE_KEYS: Record<string, string> = {
  active: 'status.active',
  advisory: 'aiSurface.types.advisory',
  archived: 'status.archived',
  assistant: 'aiSurface.types.assistant',
  assigned_sources: 'aiSurface.assignedSources',
  available: 'status.available',
  available_for_general_assistance: 'aiSurface.availableForGeneralAssistance',
  blocked: 'status.blocked',
  disabled: 'status.disabled',
  collection: 'aiSurface.types.collection',
  embeddings: 'aiConfig.capabilityEmbeddings',
  generation: 'aiConfig.capabilityGeneration',
  multimodal: 'aiConfig.capabilityMultimodal',
  object_storage: 'aiSurface.types.objectStorage',
  organization: 'aiConfig.scopeOrganization',
  not_configured: 'status.notConfigured',
  not_ready: 'status.notReady',
  needs_ai_provider: 'aiSurface.needsAiProvider',
  needs_searchable_knowledge: 'aiSurface.needsSearchableKnowledge',
  pending: 'status.pending',
  platform: 'aiConfig.scopePlatform',
  reference_tenant: 'aiSurface.types.referenceTenant',
  reranking: 'aiConfig.capabilityReranking',
  ready: 'status.ready',
  ready_for_grounded_answers: 'aiSurface.readyForGroundedAnswers',
  ready_without_ai_provider: 'aiSurface.readyWithoutAiProvider',
  unavailable: 'status.unavailable',
  unauthorized: 'errors.accessRequired',
  smoke: 'aiSurface.types.validation',
};

const AI_STUDIO_REASON_KEYS: Record<string, string> = {
  an_ai_provider_is_configured_and_knowledge_search_is_not_required: 'aiSurface.reasons.generalAssistance',
  an_enabled_provider_model_and_applicable_runtime_profile_are_configured: 'aiSurface.reasons.generativeReady',
  assistant_access_is_not_authorized: 'aiSurface.reasons.accessRequired',
  at_least_one_enabled_assistant_has_an_applicable_searchable_knowledge_scope: 'aiSurface.reasons.groundedReady',
  enterprise_search_and_searchable_organization_knowledge_are_available: 'aiSurface.reasons.groundedKnowledgeReady',
  no_complete_enabled_generative_provider_and_model_association_is_currently_configured: 'aiSurface.reasons.generativeNotConfigured',
  no_enabled_assistant_currently_has_an_applicable_searchable_knowledge_scope: 'aiSurface.reasons.groundedNotReady',
  no_searchable_governed_knowledge_is_currently_available: 'aiSurface.reasons.searchUnavailable',
  no_searchable_organization_source_is_currently_available_for_grounded_answers: 'aiSurface.reasons.knowledgeUnavailable',
  postgresql_enterprise_search_has_searchable_governed_knowledge: 'aiSurface.reasons.searchReady',
  the_assistant_is_disabled: 'aiSurface.reasons.assistantDisabled',
  the_assistant_is_not_enabled: 'aiSurface.reasons.assistantNotEnabled',
  the_configured_runtime_can_operate_without_an_external_ai_provider: 'aiSurface.reasons.providerOptional',
  this_assistant_requires_an_ai_provider_but_no_executable_provider_is_configured: 'aiSurface.reasons.providerRequired',
};

const AI_STUDIO_METRIC_KEYS: Record<string, string> = {
  assistant_response_executions: 'aiSurface.metrics.assistantResponses',
  assistant_runtime_executions: 'aiSurface.metrics.assistantRuntime',
  assistant_sessions: 'aiSurface.metrics.assistantSessions',
  chat_runtime_executions: 'aiSurface.metrics.chatRuntime',
  citation_verification_executions: 'aiSurface.metrics.citationVerification',
  llm_execution_records: 'aiSurface.metrics.llmRecords',
  llm_gateway_executions: 'aiSurface.metrics.llmGateway',
  prompt_assembly_executions: 'aiSurface.metrics.promptAssembly',
  assistants: 'aiSurface.domains.assistants',
  deterministic_search: 'aiSurface.domains.deterministicSearch',
  generative_llm: 'aiSurface.domains.generativeLlm',
  grounded_assistant: 'aiSurface.domains.groundedAssistant',
  guardrails: 'aiSurface.domains.guardrails',
  knowledge_sources: 'aiSurface.domains.knowledgeSources',
  models: 'aiSurface.domains.models',
  prompts: 'aiSurface.domains.prompts',
  providers: 'aiSurface.domains.providers',
  workflows: 'aiSurface.domains.workflows',
};

const AI_STUDIO_ENTITY_NAME_KEYS: Record<string, string> = {
  'reference-assistant': 'aiSurface.entities.referenceAssistant',
  'reference-assistant-prompt': 'aiSurface.entities.referenceAssistantPrompt',
  'reference-guardrail': 'aiSurface.entities.referenceGuardrail',
  'reference-readiness-workflow': 'aiSurface.entities.referenceReadinessWorkflow',
};

function aiStudioMetric(key: string, translate: (translationKey: string) => string): string {
  return AI_STUDIO_METRIC_KEYS[key] ? translate(AI_STUDIO_METRIC_KEYS[key]) : translate('dynamic.detailsAvailable');
}

function aiStudioEntityName(code: unknown, name: unknown, translate: (key: string) => string): string {
  const key = AI_STUDIO_ENTITY_NAME_KEYS[String(code ?? '')];
  return key ? translate(key) : asText(name, translate('dynamic.detailsAvailable'));
}

function normalizedValue(value: unknown): string {
  return String(value ?? '').trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
}

function aiStudioValue(value: unknown, translate: (key: string) => string): string {
  if (value === null || value === undefined || value === '') return translate('common.notAvailable');
  const key = AI_STUDIO_VALUE_KEYS[normalizedValue(value)];
  return key ? translate(key) : translate('dynamic.detailsAvailable');
}

function aiStudioReason(value: unknown, translate: (key: string) => string): string {
  const key = AI_STUDIO_REASON_KEYS[normalizedValue(value)];
  return key ? translate(key) : translate('dynamic.detailsAvailable');
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function asList(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item) => item && typeof item === 'object') as Record<string, unknown>[]
    : [];
}

function statusClass(ready: boolean): string {
  return ready ? 'status-dot ready' : 'status-dot degraded';
}

function readinessStatus(value: unknown): string {
  return asText(asRecord(value).status, 'pending');
}

function issueText(item: Record<string, unknown>, translate: (key: string) => string): string {
  const key = normalizedValue(item.item_id ?? item.code);
  return AI_STUDIO_VALUE_KEYS[key] ? translate(AI_STUDIO_VALUE_KEYS[key]) : translate('dynamic.detailsAvailable');
}

function MetricCard({ label, value }: { label: string; value: unknown }) {
  const { t } = useI18n();
  return (
    <article className="metric-card">
      <small>{label}</small>
      <strong>{localizedProductLabel(value, t, '0')}</strong>
    </article>
  );
}

function SummaryCards({ runtime }: { runtime: AIStudioRuntime }) {
  const { t } = useI18n();
  const capabilities = asRecord(runtime.capability_availability);
  const deterministic = asRecord(capabilities.deterministic_search);
  const grounded = asRecord(capabilities.grounded_assistant);
  const generative = asRecord(capabilities.generative_llm);
  const historical = asRecord(capabilities.historical_usage);
  const rows = [
    [t('copy.deterministic_search_ee59dc62'), deterministic.status ?? 'unavailable', deterministic.available],
    [t('copy.grounded_assistant_6fbe72e5'), grounded.status ?? 'not_ready', grounded.ready],
    [t('copy.generative_llm_9333ec3c'), generative.status ?? 'not_configured', generative.ready],
  ];
  return (
    <section className="table-card" data-ai-studio-section="capability-availability">
      <h2><LocalizedText id="copy.current_capability_availability_8efb2410" /></h2>
      <div className="grid">
        {rows.map(([label, value, ready]) => (
          <article className="card health-card" key={label as string}>
            <div className="context-card-header">
              <h2>{label as string}</h2>
              <span className={statusClass(Boolean(ready))}></span>
            </div>
            <span className="metric-value">{localizedProductLabel(value, t)}</span>
          </article>
        ))}
        <article className="metric-card">
          <small><LocalizedText id="copy.historical_llm_executions_456afa37" /></small>
          <strong>{asText(historical.llm_execution_count, '0')}</strong>
        </article>
      </div>
      <p>{aiStudioReason(deterministic.reason, t)}</p>
      <p>{aiStudioReason(grounded.reason, t)}</p>
      <p>{aiStudioReason(generative.reason, t)}</p>
      {historical.historical_executions_exist && !generative.ready ? (
        <p><LocalizedText id="copy.historical_executions_exist_no_generative_provider_i_8960b966" /></p>
      ) : null}
    </section>
  );
}

function ModelsProvidersSection({ data }: { data: Record<string, unknown> }) {
  const { t } = useI18n();
  const models = asList(data.models);
  const providers = asList(data.providers);
  return (
    <section className="table-card" data-ai-studio-section="models-providers">
      <h2><LocalizedText id="copy.models_and_providers_442a05c1" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.models_f3798f81')} value={models.length} />
        <MetricCard label={t('copy.providers_87b7c08b')} value={providers.length} />
        <MetricCard label={t('copy.configured_providers_cfa6a236')} value={providers.filter((item) => item.configuration_present).length} />
        <MetricCard label={t('copy.enabled_models_a0045fc4')} value={models.filter((item) => item.enabled).length} />
      </div>
      {models.length === 0 && providers.length === 0 ? (
        <p><LocalizedText id="copy.generative_ai_is_not_configured_deterministic_search_0e60ac44" /></p>
      ) : null}
      <table>
        <thead>
          <tr><th><LocalizedText id="copy.model_68c2cc7f" /></th><th><LocalizedText id="copy.provider_7ceee3f3" /></th><th><LocalizedText id="common.type" /></th><th><LocalizedText id="common.status" /></th><th><LocalizedText id="copy.availability_681b5b5a" /></th></tr>
        </thead>
        <tbody>
          {models.map((model) => (
            <tr key={asText(model.model_id)}>
              <td>{aiStudioEntityName(model.model_key ?? model.code, model.name, t)}<small className="table-secondary"><code>{asText(model.model_key ?? model.code)}</code></small></td>
              <td>{asText(model.provider)}</td>
              <td>{aiStudioValue(model.model_type, t)}<small className="table-secondary"><code>{asText(model.model_type)}</code></small></td>
              <td>{aiStudioValue(model.status, t)}</td>
              <td>{model.enabled ? <LocalizedText id="copy.available_7c62a142" /> : <LocalizedText id="status.unavailable" />}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function PromptsSection({ prompts }: { prompts: Record<string, unknown>[] }) {
  const { t } = useI18n();
  return (
    <section className="table-card" data-ai-studio-section="prompts">
      <h2><LocalizedText id="copy.prompts_eea5311d" /></h2>
      <table>
        <thead>
          <tr><th><LocalizedText id="copy.prompt_a817d7eb" /></th><th><LocalizedText id="common.type" /></th><th><LocalizedText id="copy.version_2da600bf" /></th><th><LocalizedText id="common.status" /></th><th><LocalizedText id="copy.assigned_assistants_1ca50d5e" /></th></tr>
        </thead>
        <tbody>
          {prompts.map((prompt) => (
            <tr key={asText(prompt.prompt_id)}>
              <td>{aiStudioEntityName(prompt.prompt_key ?? prompt.code, prompt.name, t)}<small className="table-secondary"><code>{asText(prompt.prompt_key ?? prompt.code)}</code></small></td>
              <td>{aiStudioValue(prompt.prompt_type, t)}<small className="table-secondary"><code>{asText(prompt.prompt_type)}</code></small></td>
              <td>{asText(prompt.version)}</td>
              <td>{aiStudioValue(prompt.status, t)}</td>
              <td>{asText(prompt.assigned_assistants_count, '0')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function GuardrailsSection({ guardrails }: { guardrails: Record<string, unknown>[] }) {
  const { t } = useI18n();
  return (
    <section className="table-card" data-ai-studio-section="guardrails">
      <h2><LocalizedText id="copy.guardrails_2dd5f894" /></h2>
      <table>
        <thead>
          <tr><th><LocalizedText id="copy.guardrail_11a5fd9b" /></th><th><LocalizedText id="common.type" /></th><th><LocalizedText id="copy.mode_a7b93d21" /></th><th><LocalizedText id="common.status" /></th><th><LocalizedText id="copy.assigned_assistants_1ca50d5e" /></th></tr>
        </thead>
        <tbody>
          {guardrails.map((guardrail) => (
            <tr key={asText(guardrail.guardrail_id)}>
              <td>{aiStudioEntityName(guardrail.guardrail_key ?? guardrail.code, guardrail.name, t)}<small className="table-secondary"><code>{asText(guardrail.guardrail_key ?? guardrail.code)}</code></small></td>
              <td>{aiStudioValue(guardrail.guardrail_type, t)}<small className="table-secondary"><code>{asText(guardrail.guardrail_type)}</code></small></td>
              <td>{aiStudioValue(guardrail.enforcement_mode, t)}<small className="table-secondary"><code>{asText(guardrail.enforcement_mode)}</code></small></td>
              <td>{aiStudioValue(guardrail.status, t)}</td>
              <td>{asText(guardrail.assigned_assistants_count, '0')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function WorkflowsSection({ workflows }: { workflows: Record<string, unknown>[] }) {
  const { t } = useI18n();
  return (
    <section className="table-card" data-ai-studio-section="workflows">
      <h2><LocalizedText id="copy.workflows_825ce9e9" /></h2>
      <table>
        <thead>
          <tr><th><LocalizedText id="copy.workflow_d7a48414" /></th><th><LocalizedText id="common.type" /></th><th><LocalizedText id="common.status" /></th><th><LocalizedText id="status.enabled" /></th><th><LocalizedText id="copy.steps_cdde4f20" /></th><th><LocalizedText id="copy.definition_bf1be2b7" /></th><th><LocalizedText id="copy.assigned_e24e824b" /></th><th><LocalizedText id="status.ready" /></th></tr>
        </thead>
        <tbody>
          {workflows.map((workflow) => (
            <tr key={asText(workflow.workflow_id)}>
              <td>{aiStudioEntityName(workflow.workflow_key ?? workflow.code, workflow.name, t)}<br /><small><code>{asText(workflow.workflow_key ?? workflow.code)}</code></small></td>
              <td>{aiStudioValue(workflow.workflow_type, t)}<small className="table-secondary"><code>{asText(workflow.workflow_type)}</code></small></td>
              <td>{aiStudioValue(workflow.status, t)}</td>
              <td>{workflow.enabled ? t('common.yes') : t('common.no')}</td>
              <td>{asText(workflow.steps_count, '0')}</td>
              <td>{workflow.definition_present ? t('common.yes') : t('common.no')}</td>
              <td>{asText(workflow.assigned_assistants_count, '0')}</td>
              <td>{localizedProductLabel(readinessStatus(workflow.readiness), t)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function AssistantsSection({ assistants }: { assistants: Record<string, unknown>[] }) {
  const { t } = useI18n();
  return (
    <section className="table-card" data-ai-studio-section="assistants">
      <h2><LocalizedText id="copy.assistants_127c1ab3" /></h2>
      <table>
        <thead>
          <tr><th><LocalizedText id="ask.assistant" /></th><th><LocalizedText id="copy.configuration_75416485" /></th><th><LocalizedText id="copy.assigned_sources_c3dca422" /></th><th><LocalizedText id="copy.knowledge_scope_12639c68" /></th><th><LocalizedText id="copy.searchable_organization_sources_1bdcff63" /></th><th><LocalizedText id="copy.availability_681b5b5a" /></th></tr>
        </thead>
        <tbody>
          {assistants.map((assistant) => (
            <tr key={asText(assistant.assistant_id)}>
              <td>{aiStudioEntityName(assistant.assistant_key, assistant.assistant_name, t)}<small className="table-secondary"><code>{asText(assistant.assistant_key)}</code></small></td>
              <td>{localizedProductLabel(assistant.assistant_status, t)}</td>
              <td>{asText(assistant.assigned_knowledge_sources_count, '0')}</td>
              <td>{aiStudioValue(asRecord(assistant.availability).knowledge_scope_type, t)}</td>
              <td>{asText(assistant.searchable_organization_sources_count, '0')}</td>
              <td><strong>{aiStudioValue(asRecord(assistant.availability).status, t)}</strong><br /><small>{aiStudioReason(asRecord(assistant.availability).reason, t)}</small></td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function KnowledgeSourcesSection({ sources }: { sources: Record<string, unknown>[] }) {
  const { t } = useI18n();
  return (
    <section className="table-card" data-ai-studio-section="knowledge-sources">
      <h2><LocalizedText id="copy.knowledge_sources_a70fa55f" /></h2>
      <table>
        <thead>
          <tr><th><LocalizedText id="copy.source_6da13add" /></th><th><LocalizedText id="common.type" /></th><th><LocalizedText id="copy.collection_30c54a96" /></th><th><LocalizedText id="common.status" /></th><th><LocalizedText id="status.configured" /></th><th><LocalizedText id="copy.assistant_binding_84bf0d75" /></th><th><LocalizedText id="status.ready" /></th></tr>
        </thead>
        <tbody>
          {sources.map((source) => (
            <tr key={asText(source.source_id)}>
              <td><details><summary><LocalizedText id="common.technicalId" /></summary><small>{asText(source.source_id)}</small></details></td>
              <td>{aiStudioValue(source.source_type, t)}<small className="table-secondary"><code>{asText(source.source_type)}</code></small></td>
              <td><details><summary><LocalizedText id="common.technicalId" /></summary><small>{asText(source.collection_id)}</small></details></td>
              <td>{aiStudioValue(source.status, t)}</td>
              <td>{source.configured ? t('common.yes') : t('common.no')}</td>
              <td><small>{asText(source.assistant_binding)}</small></td>
              <td>{localizedProductLabel(readinessStatus(source.readiness), t)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function RuntimeSection({ executions }: { executions: Record<string, unknown> }) {
  const { t } = useI18n();
  return (
    <section className="table-card" data-ai-studio-section="runtime-executions">
      <h2><LocalizedText id="copy.historical_runtime_usage_4aa961a5" /></h2>
      <p><LocalizedText id="copy.persisted_execution_history_is_evidence_of_past_usag_9c586626" /></p>
      <div className="metrics-grid">
        {Object.entries(executions)
          .filter(([, value]) => typeof value === 'number')
          .map(([key, value]) => (
            <MetricCard key={key} label={aiStudioMetric(key, t)} value={value} />
          ))}
      </div>
    </section>
  );
}

function PolicySection({ policy }: { policy: Record<string, unknown> }) {
  const { t } = useI18n();
  const readiness = asRecord(policy.readiness_by_domain);
  return (
    <section className="table-card" data-ai-studio-section="policy-readiness">
      <h2><LocalizedText id="copy.policy_and_readiness_fe2468d5" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.ai_provider_f81714b5')} value={policy.ai_optional ? t('copy.optional_0c6c4102') : t('copy.required_eed6bfb4')} />
        <MetricCard label={t('copy.operation_without_ai_22a92b61')} value={policy.platform_works_without_ai ? t('copy.available_7c62a142') : t('status.unavailable')} />
        <MetricCard label={t('copy.llm_without_configuration_deacebe2')} value={policy.llm_execution_disabled_when_not_configured ? t('status.disabled') : t('status.enabled')} />
        <MetricCard label={t('copy.qdrant_388a01a6')} value={policy.qdrant_not_required ? t('copy.optional_0c6c4102') : t('copy.required_eed6bfb4')} />
        <MetricCard label={t('copy.embeddings_f428bd5b')} value={policy.embeddings_not_required ? t('copy.optional_0c6c4102') : t('copy.required_eed6bfb4')} />
      </div>
      <div className="metrics-grid">
        {Object.entries(readiness).map(([key, value]) => (
          <MetricCard key={key} label={aiStudioMetric(key, t)} value={value ? t('status.ready') : t('status.notReady')} />
        ))}
      </div>
    </section>
  );
}

function AuditDiagnosticsSection({ diagnostics }: { diagnostics: Record<string, unknown> }) {
  const { t } = useI18n();
  const groups = [
    ['aiSurface.diagnostics.blocking', diagnostics.blocking_issues ?? []],
    ['aiSurface.diagnostics.warnings', diagnostics.warnings ?? []],
    ['aiSurface.diagnostics.pending', diagnostics.pending_capabilities ?? []],
    ['aiSurface.diagnostics.degraded', diagnostics.degraded_items ?? []],
  ];
  return (
    <section className="table-card" data-ai-studio-section="audit-diagnostics">
      <h2><LocalizedText id="copy.audit_and_diagnostics_1b25a5f4" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.audit_events_9e7d8c07')} value={diagnostics.audit_events_count} />
        <MetricCard label={t('copy.recent_audit_1c6069dd')} value={asList(diagnostics.recent_audit_events).length} />
      </div>
      <div className="alerts-grid">
        {groups.map(([title, values]) => (
          <article className="context-card" key={title as string}>
            <div className="context-card-header">
              <strong>{t(title as string)}</strong>
              <span>{(values as Record<string, unknown>[]).length}</span>
            </div>
            {(values as Record<string, unknown>[]).length > 0 ? (
              <ul className="compact-list">
                {(values as Record<string, unknown>[]).map((item, index) => (
                  <li key={`${title}-${index}`}>{issueText(item, t)}</li>
                ))}
              </ul>
            ) : (
              <p><LocalizedText id="common.noItems" /></p>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

export function AIStudioWorkspace() {
  const { t } = useI18n();
  const { organization } = useOrganization();
  const [runtime, setRuntime] = useState<AIStudioRuntime | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<'assistants' | 'prompts' | 'guardrails' | 'models'>('assistants');
  const requestVersion = useRef(0);

  const load = useCallback(async () => {
      const version = ++requestVersion.current;
      setLoading(true);
      setError(null);
      try {
        const payload = await getAIStudioRuntime();
        if (version === requestVersion.current) setRuntime(payload);
      } catch (loadError) {
        if (version === requestVersion.current) {
          setError(localizedApiError(loadError, t, 'feedback.aiStudioRuntimeUnavailable'));
        }
      } finally {
        if (version === requestVersion.current) setLoading(false);
      }
  }, [t]);

  useEffect(() => {
    setRuntime(null);
    void load();
    return () => { requestVersion.current += 1; };
  }, [load, organization?.id]);

  const auditDiagnostics = useMemo(
    () => asRecord(runtime?.audit_diagnostics ?? runtime?.diagnostics),
    [runtime],
  );
  const viewLabels = {
    assistants: t('copy.assistants_127c1ab3'),
    prompts: t('copy.prompts_eea5311d'),
    guardrails: t('copy.guardrails_2dd5f894'),
    models: t('copy.models_f3798f81'),
  };

  if (loading && !runtime) {
    return (
      <section className="card" data-ai-studio-section="loading">
        <h2><LocalizedText id="copy.loading_ai_configuration_24a15b77" /></h2>
        <p><LocalizedText id="copy.retrieving_assistants_and_their_current_availability_4642430b" /></p>
      </section>
    );
  }

  if (!runtime) {
    return (
      <section className="card" data-ai-studio-section="error">
        <h2><LocalizedText id="copy.ai_studio_unavailable_a2e977b4" /></h2>
        <p>{error ?? <LocalizedText id="copy.no_ai_studio_runtime_payload_was_returned_77d66564" />}</p>
        <button className="button secondary" type="button" onClick={() => void load()}><LocalizedText id="common.actions.retry" /></button>
      </section>
    );
  }

  return (
    <div className="product-workspace" data-ai-studio="ready">
      {error ? <p className="context-message context-error" role="alert">{t('dynamic.latestAssistantStatusError')} <button className="button secondary" type="button" onClick={() => void load()}><LocalizedText id="common.actions.retry" /></button></p> : null}
      {loading ? <p className="context-message" role="status"><LocalizedText id="copy.refreshing_assistant_availability_a5fc5ea4" /></p> : null}
      <section className="table-card" data-ai-studio-section="summary"><div className="section-header"><div><span className="eyebrow">{t('dynamic.assistantConfigurationFor', { organization: organization?.name ?? t('dynamic.selectedOrganization') })}</span><h2><LocalizedText id="pages.ai.title" /></h2><p><LocalizedText id="copy.review_available_assistants_and_the_configuration_su_8c9ce38c" /></p></div><a className="button secondary" href="/ask"><LocalizedText id="copy.open_ask_ai_40e44973" /></a></div>
        <div className="workspace-tabs" role="group">{(['assistants', 'prompts', 'guardrails', 'models'] as const).map((view) => <button aria-pressed={activeView === view} className={activeView === view ? 'is-active' : ''} key={view} onClick={() => setActiveView(view)} type="button">{viewLabels[view]}</button>)}</div>
      </section>
      <SummaryCards runtime={runtime} />
      {activeView === 'assistants' ? <AssistantsSection assistants={runtime.assistants} /> : null}
      {activeView === 'prompts' ? <PromptsSection prompts={runtime.prompts} /> : null}
      {activeView === 'guardrails' ? <GuardrailsSection guardrails={runtime.guardrails} /> : null}
      {activeView === 'models' ? <ModelsProvidersSection data={asRecord(runtime.models_and_providers)} /> : null}
      <details className="advanced-panel"><summary><LocalizedText id="copy.historical_usage_and_advanced_ai_diagnostics_2edf7e64" /></summary><div className="advanced-panel-content"><WorkflowsSection workflows={runtime.workflows} /><KnowledgeSourcesSection sources={runtime.knowledge_sources} /><RuntimeSection executions={runtime.runtime_executions} /><PolicySection policy={runtime.policy_readiness} /><AuditDiagnosticsSection diagnostics={auditDiagnostics} /></div></details>
    </div>
  );
}
