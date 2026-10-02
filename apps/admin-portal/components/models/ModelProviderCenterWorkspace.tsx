'use client';

import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useI18n } from '../../i18n/I18nProvider';
import { ActionConfirmationDialog } from '../layout/ActionConfirmationDialog';
import {
  createModelConfiguration,
  createProviderConfiguration,
  getAIConfigurationWorkspace,
  setDefaultModel,
  setModelArchived,
  setModelEnabled,
  setProviderArchived,
  setProviderEnabled,
  updateModelConfiguration,
  updateProviderConfiguration,
  validateModel,
  validateProvider,
  type AIConfigurationWorkspace,
  type ModelConfiguration,
  type ModelInput,
  type ProviderConfiguration,
  type ProviderInput,
  type ValidationEvidence,
} from '../../lib/model-provider-center-api';
import { PlatformApiError } from '../../lib/platform-api';
import { localizedApiError, localizedProductLabel } from '../../lib/presentation';

type WorkspaceView = 'providers' | 'models';

const AI_CONFIGURATION_LABEL_KEYS: Record<string, string> = {
  generation: 'aiConfig.capabilityGeneration',
  chat: 'aiConfig.capabilityChat',
  embeddings: 'aiConfig.capabilityEmbeddings',
  reranking: 'aiConfig.capabilityReranking',
  multimodal: 'aiConfig.capabilityMultimodal',
  env: 'aiConfig.environmentReference',
  available: 'status.ready',
  adapter_unavailable: 'status.unavailable',
  provider_unavailable: 'status.unavailable',
  never_validated: 'aiConfig.neverValidated',
  validation_stale: 'aiConfig.stale',
  validation_failed: 'status.failed',
  archived: 'aiConfig.statusArchived',
  succeeded: 'status.ready',
  organization: 'aiConfig.scopeOrganization',
  platform: 'aiConfig.scopePlatform',
  provider_configuration_archived: 'aiConfig.reasons.providerArchived',
  provider_configuration_disabled: 'aiConfig.reasons.providerDisabled',
  provider_adapter_not_executable: 'aiConfig.reasons.adapterUnavailable',
  provider_never_validated: 'aiConfig.reasons.providerNeverValidated',
  provider_validation_stale: 'aiConfig.reasons.providerValidationStale',
  provider_validation_failed: 'aiConfig.reasons.providerValidationFailed',
  model_configuration_archived: 'aiConfig.reasons.modelArchived',
  model_configuration_disabled: 'aiConfig.reasons.modelDisabled',
  model_never_validated: 'aiConfig.reasons.modelNeverValidated',
  model_validation_stale: 'aiConfig.reasons.modelValidationStale',
  model_validation_failed: 'aiConfig.reasons.modelValidationFailed',
};

type ConfirmationRequest = {
  confirmLabel: string;
  description: string;
  title: string;
  action: () => Promise<boolean>;
};

function aiConfigurationLabel(
  value: unknown,
  translate: (key: string) => string,
): string {
  const key = AI_CONFIGURATION_LABEL_KEYS[String(value ?? '').trim().toLowerCase()];
  return key ? translate(key) : localizedProductLabel(value, translate);
}

function aiConfigurationReason(value: unknown, translate: (key: string) => string): string {
  const normalized = String(value ?? '').trim().toLowerCase().replace(/[\s-]+/g, '_');
  const key = AI_CONFIGURATION_LABEL_KEYS[normalized];
  return key ? translate(key) : translate('aiConfig.reasonUnavailable');
}

function parseConfiguration(value: string, invalidMessage: string): Record<string, unknown> {
  const normalized = value.trim();
  if (!normalized) return {};
  try {
    const parsed = JSON.parse(normalized) as unknown;
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error(invalidMessage);
    return parsed as Record<string, unknown>;
  } catch {
    throw new Error(invalidMessage);
  }
}

function configurationText(value: Record<string, unknown>): string {
  return Object.keys(value).length ? JSON.stringify(value, null, 2) : '';
}

function EvidenceSummary({ evidence }: { evidence: ValidationEvidence | null }) {
  const { date, t } = useI18n();
  if (!evidence) return <span>{t('aiConfig.neverValidated')}</span>;
  return (
    <span>
      {aiConfigurationLabel(evidence.status, t)}
      {' · '}
      {date(evidence.evaluated_at)}
      {evidence.evidence_status === 'stale' ? ` · ${t('aiConfig.stale')}` : ''}
      {evidence.sanitized_error ? <><br /><small>{aiConfigurationReason(evidence.error_code, t)}</small></> : null}
    </span>
  );
}

function ProviderForm({
  adapters,
  credentialResolverTypes,
  disabled,
  editing,
  onCancel,
  onSubmit,
}: {
  adapters: AIConfigurationWorkspace['adapters'];
  credentialResolverTypes: string[];
  disabled: boolean;
  editing: ProviderConfiguration | null;
  onCancel: () => void;
  onSubmit: (payload: ProviderInput | Partial<ProviderInput>) => Promise<boolean>;
}) {
  const { t } = useI18n();
  const executableAdapters = adapters.filter((adapter) => adapter.execution_supported);
  const configurationAdapter = adapters.find((adapter) => adapter.configuration_supported);
  const [providerKey, setProviderKey] = useState(editing?.provider_key ?? '');
  const [displayName, setDisplayName] = useState(editing?.display_name ?? '');
  const [adapterType, setAdapterType] = useState(
    editing?.adapter_type
      ?? executableAdapters[0]?.adapter_type
      ?? configurationAdapter?.adapter_type
      ?? '',
  );
  const [description, setDescription] = useState(editing?.description ?? '');
  const [endpointUrl, setEndpointUrl] = useState(editing?.endpoint_url ?? '');
  const [resolverType, setResolverType] = useState(credentialResolverTypes[0] ?? '');
  const [credentialReference, setCredentialReference] = useState('');
  const [clearCredential, setClearCredential] = useState(false);
  const [configuration, setConfiguration] = useState(configurationText(editing?.configuration ?? {}));
  const [formError, setFormError] = useState<string | null>(null);
  const selectedAdapter = adapters.find((adapter) => adapter.adapter_type === adapterType);
  const selectedAdapterExecutable = Boolean(selectedAdapter?.execution_supported);
  const providerHelpKey = selectedAdapterExecutable
    ? 'aiConfig.providerHelp'
    : selectedAdapter?.configuration_supported
      ? 'aiConfig.configurationOnlyProviderHelp'
      : 'aiConfig.noAdapterContractHelp';

  async function submit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    try {
      const common = {
        display_name: displayName,
        description: description || (editing ? null : undefined),
        endpoint_url: endpointUrl || (editing ? null : undefined),
        configuration: parseConfiguration(configuration, t('aiConfig.invalidConfiguration')),
        ...(credentialReference
          ? { credential: { resolver_type: resolverType, reference: credentialReference } }
          : {}),
        ...(editing && clearCredential ? { clear_credential: true } : {}),
      };
      const saved = await onSubmit(
        editing
          ? common
          : {
              ...common,
              provider_key: providerKey,
              adapter_type: adapterType,
              enabled: false,
            },
      );
      if (saved && !editing) {
        setProviderKey('');
        setDisplayName('');
        setDescription('');
        setEndpointUrl('');
        setCredentialReference('');
        setConfiguration('');
      }
    } catch (cause) {
      setFormError(cause instanceof Error ? cause.message : t('aiConfig.operationFailed'));
    }
  }

  return (
    <form className="table-card model-provider-form" onSubmit={submit}>
      <div className="section-header">
        <h2>{editing ? t('aiConfig.editProvider') : t('aiConfig.addProvider')}</h2>
        <p>{t(providerHelpKey)}</p>
      </div>
      <div className="model-provider-form-grid">
        {!editing ? (
          <label className="model-provider-form-field" htmlFor="provider-key">
            <span className="field-label">{t('common.code')}</span>
            <input className="field-control" disabled={disabled} id="provider-key" onChange={(event) => setProviderKey(event.target.value)} required value={providerKey} />
          </label>
        ) : null}
        <label className="model-provider-form-field" htmlFor="provider-display-name">
          <span className="field-label">{t('common.name')}</span>
          <input className="field-control" disabled={disabled} id="provider-display-name" onChange={(event) => setDisplayName(event.target.value)} required value={displayName} />
        </label>
        <label className="model-provider-form-field" htmlFor="provider-adapter">
          <span className="field-label">{t('aiConfig.adapter')}</span>
          <select
            aria-describedby={selectedAdapter?.availability_reason ? 'provider-adapter-availability' : undefined}
            className="field-control"
            disabled={disabled || Boolean(editing) || !executableAdapters.length}
            id="provider-adapter"
            onChange={(event) => setAdapterType(event.target.value)}
            required
            value={adapterType}
          >
            {editing ? (
              <option value={adapterType}>
                {selectedAdapterExecutable
                  ? localizedProductLabel(adapterType, t)
                  : t('aiConfig.configurationOnlyAdapter')}
              </option>
            ) : executableAdapters.length ? (
              adapters.map((adapter) => (
                adapter.execution_supported ? (
                  <option key={adapter.adapter_type} value={adapter.adapter_type}>
                    {localizedProductLabel(adapter.adapter_type, t)}
                  </option>
                ) : null
              ))
            ) : (
              <option value={adapterType}>{t('aiConfig.noExecutableAdapterOption')}</option>
            )}
          </select>
        </label>
        <label className="model-provider-form-field" htmlFor="provider-description">
          <span className="field-label">{t('common.description')}</span>
          <input className="field-control" disabled={disabled} id="provider-description" onChange={(event) => setDescription(event.target.value)} value={description} />
        </label>
        <label className="model-provider-form-field" htmlFor="provider-endpoint">
          <span className="field-label">{t('aiConfig.endpoint')}</span>
          <input className="field-control" disabled={disabled} id="provider-endpoint" onChange={(event) => setEndpointUrl(event.target.value)} placeholder={t('aiConfig.endpointHelp')} type="url" value={endpointUrl} />
        </label>
        <label className="model-provider-form-field" htmlFor="provider-credential-resolver">
          <span className="field-label">{t('aiConfig.credentialResolver')}</span>
          <select className="field-control" disabled={disabled || !credentialResolverTypes.length} id="provider-credential-resolver" onChange={(event) => setResolverType(event.target.value)} value={resolverType}>
            {credentialResolverTypes.map((resolver) => (
              <option key={resolver} value={resolver}>{aiConfigurationLabel(resolver, t)}</option>
            ))}
          </select>
        </label>
        <label className="model-provider-form-field model-provider-form-wide" htmlFor="provider-credential-reference">
          <span className="field-label">{t('aiConfig.credentialReference')}</span>
          <input
            autoComplete="off"
            className="field-control"
            disabled={disabled || !resolverType}
            id="provider-credential-reference"
            onChange={(event) => setCredentialReference(event.target.value)}
            placeholder={editing?.credential_configured ? t('aiConfig.credentialUnchanged') : t('aiConfig.credentialReferenceHelp')}
            value={credentialReference}
          />
        </label>
        {selectedAdapter?.availability_reason ? (
          <div className="model-provider-form-notice model-provider-form-wide" id="provider-adapter-availability">
            <small>{aiConfigurationReason(selectedAdapter.availability_reason_code, t)}</small>
          </div>
        ) : null}
        {editing?.credential_configured ? (
          <label className="model-provider-form-checkbox model-provider-form-wide" htmlFor="provider-clear-credential">
            <input checked={clearCredential} disabled={disabled} id="provider-clear-credential" onChange={(event) => setClearCredential(event.target.checked)} type="checkbox" />
            <span>{t('aiConfig.clearCredential')}</span>
          </label>
        ) : null}
        <label className="model-provider-form-field model-provider-form-wide" htmlFor="provider-configuration">
          <span className="field-label">{t('aiConfig.nonSecretConfiguration')}</span>
          <textarea className="field-control" disabled={disabled} id="provider-configuration" onChange={(event) => setConfiguration(event.target.value)} rows={6} value={configuration} />
        </label>
        {formError ? <p className="form-error model-provider-form-wide" role="alert">{formError}</p> : null}
        <div className="model-provider-form-actions model-provider-form-wide">
          <button className="button" disabled={disabled || (!editing && !selectedAdapter?.configuration_supported)} type="submit">{t('common.actions.save')}</button>
          {editing ? <button className="button secondary" disabled={disabled} onClick={onCancel} type="button">{t('common.actions.cancel')}</button> : null}
        </div>
      </div>
    </form>
  );
}

function ModelForm({
  modelCapabilities,
  providers,
  disabled,
  editing,
  onCancel,
  onSubmit,
}: {
  modelCapabilities: string[];
  providers: ProviderConfiguration[];
  disabled: boolean;
  editing: ModelConfiguration | null;
  onCancel: () => void;
  onSubmit: (payload: ModelInput | Partial<ModelInput>) => Promise<boolean>;
}) {
  const { t } = useI18n();
  const activeProviders = providers.filter((item) => item.lifecycle_status === 'active');
  const [providerId, setProviderId] = useState(editing?.provider_configuration_id ?? activeProviders[0]?.id ?? '');
  const [modelKey, setModelKey] = useState(editing?.model_key ?? '');
  const [displayName, setDisplayName] = useState(editing?.display_name ?? '');
  const [modelIdentifier, setModelIdentifier] = useState(editing?.model_identifier ?? '');
  const [capability, setCapability] = useState(editing?.capability ?? 'generation');
  const [defaultScope, setDefaultScope] = useState(editing?.default_scope ?? 'organization');
  const [configuration, setConfiguration] = useState(configurationText(editing?.configuration ?? {}));
  const [formError, setFormError] = useState<string | null>(null);
  const capabilityOptions = Array.from(new Set([
    ...(editing?.capability ? [editing.capability] : []),
    ...modelCapabilities,
  ]));

  async function submit(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    try {
      const common = {
        provider_configuration_id: providerId,
        display_name: displayName,
        model_identifier: modelIdentifier,
        capability,
        default_scope: defaultScope,
        configuration: parseConfiguration(configuration, t('aiConfig.invalidConfiguration')),
      };
      const saved = await onSubmit(
        editing
          ? common
          : {
              ...common,
              model_key: modelKey,
              enabled: false,
            },
      );
      if (saved && !editing) {
        setModelKey('');
        setDisplayName('');
        setModelIdentifier('');
        setConfiguration('');
      }
    } catch (cause) {
      setFormError(cause instanceof Error ? cause.message : t('aiConfig.operationFailed'));
    }
  }

  return (
    <form className="table-card model-provider-form" onSubmit={submit}>
      <div className="section-header">
        <h2>{editing ? t('aiConfig.editModel') : t('aiConfig.addModel')}</h2>
        <p>{t('aiConfig.modelHelp')}</p>
      </div>
      <div className="model-provider-form-grid">
        <label className="model-provider-form-field" htmlFor="model-provider">
          <span className="field-label">{t('aiConfig.provider')}</span>
          <select
            className="field-control"
            disabled={disabled}
            id="model-provider"
            onChange={(event) => {
              setProviderId(event.target.value);
            }}
            required
            value={providerId}
          >
            {activeProviders.map((provider) => <option key={provider.id} value={provider.id}>{provider.display_name}</option>)}
          </select>
        </label>
        {!editing ? (
          <label className="model-provider-form-field" htmlFor="model-key">
            <span className="field-label">{t('common.code')}</span>
            <input className="field-control" disabled={disabled} id="model-key" onChange={(event) => setModelKey(event.target.value)} required value={modelKey} />
          </label>
        ) : null}
        <label className="model-provider-form-field" htmlFor="model-display-name">
          <span className="field-label">{t('common.name')}</span>
          <input className="field-control" disabled={disabled} id="model-display-name" onChange={(event) => setDisplayName(event.target.value)} required value={displayName} />
        </label>
        <label className="model-provider-form-field" htmlFor="model-identifier">
          <span className="field-label">{t('aiConfig.modelIdentifier')}</span>
          <input className="field-control" disabled={disabled} id="model-identifier" onChange={(event) => setModelIdentifier(event.target.value)} required value={modelIdentifier} />
        </label>
        <label className="model-provider-form-field" htmlFor="model-capability">
          <span className="field-label">{t('aiConfig.capability')}</span>
          <select className="field-control" disabled={disabled || !capabilityOptions.length} id="model-capability" onChange={(event) => setCapability(event.target.value)} required value={capability}>
            {!capabilityOptions.length ? <option value="">{t('aiConfig.noSupportedCapabilities')}</option> : null}
            {capabilityOptions.map((item) => (
              <option key={item} value={item}>{aiConfigurationLabel(item, t)}</option>
            ))}
          </select>
        </label>
        <label className="model-provider-form-field" htmlFor="model-default-scope">
          <span className="field-label">{t('aiConfig.defaultScope')}</span>
          <select className="field-control" disabled={disabled} id="model-default-scope" onChange={(event) => setDefaultScope(event.target.value)} required value={defaultScope}>
            {Array.from(new Set([defaultScope, 'organization'])).map((scope) => <option key={scope} value={scope}>{AI_CONFIGURATION_LABEL_KEYS[scope] ? aiConfigurationLabel(scope, t) : `${t('dynamic.detailsAvailable')} (${scope})`}</option>)}
          </select>
        </label>
        <label className="model-provider-form-field model-provider-form-wide" htmlFor="model-configuration">
          <span className="field-label">{t('aiConfig.nonSecretConfiguration')}</span>
          <textarea className="field-control" disabled={disabled} id="model-configuration" onChange={(event) => setConfiguration(event.target.value)} rows={6} value={configuration} />
        </label>
        {formError ? <p className="form-error model-provider-form-wide" role="alert">{formError}</p> : null}
        <div className="model-provider-form-actions model-provider-form-wide">
          <button className="button" disabled={disabled || !providerId || !capability} type="submit">{t('common.actions.save')}</button>
          {editing ? <button className="button secondary" disabled={disabled} onClick={onCancel} type="button">{t('common.actions.cancel')}</button> : null}
        </div>
      </div>
    </form>
  );
}

export function ModelProviderCenterWorkspace() {
  const { t } = useI18n();
  const [runtime, setRuntime] = useState<AIConfigurationWorkspace | null>(null);
  const [view, setView] = useState<WorkspaceView>('providers');
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editingProvider, setEditingProvider] = useState<ProviderConfiguration | null>(null);
  const [editingModel, setEditingModel] = useState<ModelConfiguration | null>(null);
  const [capabilityFilter, setCapabilityFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [confirmation, setConfirmation] = useState<ConfirmationRequest | null>(null);
  const mutationInFlight = useRef(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    setErrorStatus(null);
    try {
      setRuntime(await getAIConfigurationWorkspace());
    } catch (cause) {
      setErrorStatus(cause instanceof PlatformApiError ? cause.status : null);
      setError(localizedApiError(cause, t, 'aiConfig.unavailable'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const mutate = useCallback(async (operation: () => Promise<unknown>, successMessage: string) => {
    if (mutationInFlight.current) return false;
    mutationInFlight.current = true;
    setPending(true);
    setError(null);
    setNotice(null);
    try {
      await operation();
      setRuntime(await getAIConfigurationWorkspace());
      setNotice(successMessage);
      return true;
    } catch (cause) {
      setError(localizedApiError(cause, t, 'aiConfig.operationFailed'));
      return false;
    } finally {
      mutationInFlight.current = false;
      setPending(false);
    }
  }, [t]);

  const filteredModels = useMemo(() => {
    if (!runtime) return [];
    return runtime.models.filter((model) => (
      (!capabilityFilter || model.capability === capabilityFilter)
      && (!statusFilter || model.availability_status === statusFilter)
    ));
  }, [capabilityFilter, runtime, statusFilter]);
  const capabilityOptions = useMemo(
    () => Array.from(new Set([
      ...(runtime?.model_capabilities ?? []),
      ...(runtime?.models.map((model) => model.capability) ?? []),
    ])).sort(),
    [runtime],
  );

  if (loading && !runtime) {
    return <section className="card" role="status"><h2>{t('aiConfig.loading')}</h2></section>;
  }
  if (!runtime) {
    if (errorStatus === 403) {
      return (
        <section className="card workspace-state">
          <span className="eyebrow">{t('copy.access_required_3d2f1a2e')}</span>
          <h2>{t('navigation.aiConfiguration')}</h2>
          <p>{error}</p>
        </section>
      );
    }
    return (
      <section className="card">
        <h2>{t('aiConfig.unavailable')}</h2>
        <p>{error}</p>
        <button className="button secondary" onClick={() => void refresh()} type="button">{t('common.actions.retry')}</button>
      </section>
    );
  }

  const providerAdmin = runtime.capabilities.administer_providers;
  const modelAdmin = runtime.capabilities.administer_models;
  const canValidate = runtime.capabilities.validate;
  const runtimeHasExecutableAdapters = runtime.adapters.some((adapter) => adapter.execution_supported);
  const runtimeHasConfigurationAdapter = runtime.adapters.some((adapter) => adapter.configuration_supported);
  const runConfirmedAction = async () => {
    if (!confirmation || mutationInFlight.current) return;
    await confirmation.action();
    setConfirmation(null);
  };

  return (
    <div className="model-provider-workspace">
      <section className="table-card">
        <div className="section-header">
          <span className="eyebrow">{t('pages.ai.section')}</span>
          <h2>{t('navigation.aiConfiguration')}</h2>
          <p>{t('aiConfig.description')}</p>
        </div>
        <div className="metrics-grid">
          <article className="metric-card"><small>{t('aiConfig.providers')}</small><strong>{runtime.provider_count}</strong></article>
          <article className="metric-card"><small>{t('aiConfig.availableProviders')}</small><strong>{runtime.available_provider_count}</strong></article>
          <article className="metric-card"><small>{t('aiConfig.models')}</small><strong>{runtime.model_count}</strong></article>
          <article className="metric-card"><small>{t('aiConfig.availableModels')}</small><strong>{runtime.available_model_count}</strong></article>
        </div>
        <p className="context-message">{t('aiConfig.optional')}</p>
        {!runtimeHasExecutableAdapters ? (
          <p className="context-message">
            {t(runtimeHasConfigurationAdapter ? 'aiConfig.noExecutableAdapters' : 'aiConfig.noAdapterContractHelp')}
          </p>
        ) : null}
        <div className="workspace-tabs" role="tablist">
          <button aria-selected={view === 'providers'} className={view === 'providers' ? 'is-active' : ''} onClick={() => setView('providers')} role="tab" type="button">{t('aiConfig.providers')}</button>
          <button aria-selected={view === 'models'} className={view === 'models' ? 'is-active' : ''} onClick={() => setView('models')} role="tab" type="button">{t('aiConfig.models')}</button>
        </div>
        {notice ? <p className="form-success" role="status">{notice}</p> : null}
        {error ? <p className="form-error" role="alert">{error}</p> : null}
      </section>

      {view === 'providers' ? (
        <>
          {!providerAdmin ? <section className="card"><p>{t('aiConfig.readOnly')}</p></section> : (
            <ProviderForm
              key={editingProvider?.id ?? 'new-provider'}
              adapters={runtime.adapters}
              credentialResolverTypes={runtime.credential_resolver_types}
              disabled={pending}
              editing={editingProvider}
              onCancel={() => setEditingProvider(null)}
              onSubmit={async (payload) => {
                const saved = await mutate(
                  () => editingProvider
                    ? updateProviderConfiguration(editingProvider.id, payload)
                    : createProviderConfiguration(payload as ProviderInput),
                  t('aiConfig.providerSaved'),
                );
                if (saved) setEditingProvider(null);
                return saved;
              }}
            />
          )}
          <section className="table-card">
            <h2>{t('aiConfig.providers')}</h2>
            {!runtime.providers.length ? <p className="model-provider-empty-state">{t('aiConfig.noProviders')}</p> : (
              <table>
                <thead><tr><th>{t('common.name')}</th><th>{t('aiConfig.adapter')}</th><th>{t('common.status')}</th><th>{t('common.ready')}</th><th>{t('aiConfig.credential')}</th><th>{t('aiConfig.lastValidation')}</th><th>{t('common.actionColumn')}</th></tr></thead>
                <tbody>
                  {runtime.providers.map((provider) => (
                    <tr key={provider.id}>
                      <td>{provider.display_name}<br /><small>{provider.provider_key}</small></td>
                      <td>
                        {runtime.adapters.find((adapter) => (
                          adapter.adapter_type === provider.adapter_type
                          && adapter.execution_supported
                        ))
                          ? localizedProductLabel(provider.adapter_type, t)
                          : t('aiConfig.configurationOnlyAdapter')}
                      </td>
                      <td>{aiConfigurationLabel(provider.lifecycle_status, t)} · {provider.enabled ? t('common.enabled') : t('aiConfig.disabled')}</td>
                      <td>
                        {aiConfigurationLabel(provider.availability_status, t)}
                        {!provider.available && provider.runtime_actions.enable.reason ? (
                          <><br /><small>{aiConfigurationReason(provider.runtime_actions.enable.reason_code, t)}</small></>
                        ) : null}
                      </td>
                      <td>{provider.credential_configured ? t('aiConfig.configured') : t('aiConfig.notConfigured')}</td>
                      <td><EvidenceSummary evidence={provider.latest_validation} /></td>
                      <td>
                        <div className="button-row">
                          {providerAdmin && provider.lifecycle_status === 'active' ? <button className="button secondary" disabled={pending} onClick={() => setEditingProvider(provider)} type="button">{t('aiConfig.edit')}</button> : null}
                          {canValidate && provider.lifecycle_status === 'active' ? <button className="button secondary" disabled={pending || !provider.runtime_actions.validate.allowed} onClick={() => void mutate(() => validateProvider(provider.id), t('aiConfig.validationRecorded'))} title={provider.runtime_actions.validate.reason_code ? aiConfigurationReason(provider.runtime_actions.validate.reason_code, t) : undefined} type="button">{t('aiConfig.validate')}</button> : null}
                          {providerAdmin && provider.lifecycle_status === 'active' ? provider.enabled ? <button className="button danger administrative-destructive-action" disabled={pending || !provider.runtime_actions.enable.allowed} onClick={() => setConfirmation({ title: t('confirmation.disableProviderTitle', { name: provider.display_name }), description: t('confirmation.disableProviderEffect'), confirmLabel: t('aiConfig.disable'), action: () => mutate(() => setProviderEnabled(provider.id, false), t('aiConfig.providerSaved')) })} title={provider.runtime_actions.enable.reason_code ? aiConfigurationReason(provider.runtime_actions.enable.reason_code, t) : undefined} type="button">{t('aiConfig.disable')}</button> : <button className="button secondary" disabled={pending || !provider.runtime_actions.enable.allowed} onClick={() => void mutate(() => setProviderEnabled(provider.id, true), t('aiConfig.providerSaved'))} title={provider.runtime_actions.enable.reason_code ? aiConfigurationReason(provider.runtime_actions.enable.reason_code, t) : undefined} type="button">{t('aiConfig.enable')}</button> : null}
                          {providerAdmin ? provider.lifecycle_status === 'active' ? <button className="button danger administrative-destructive-action" disabled={pending} onClick={() => setConfirmation({ title: t('confirmation.archiveProviderTitle', { name: provider.display_name }), description: t('confirmation.archiveProviderEffect'), confirmLabel: t('aiConfig.archive'), action: () => mutate(() => setProviderArchived(provider.id, true), t('aiConfig.providerSaved')) })} type="button">{t('aiConfig.archive')}</button> : <button className="button secondary" disabled={pending} onClick={() => void mutate(() => setProviderArchived(provider.id, false), t('aiConfig.providerSaved'))} type="button">{t('aiConfig.restore')}</button> : null}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      ) : (
        <>
          {!modelAdmin ? <section className="card"><p>{t('aiConfig.readOnly')}</p></section> : runtime.providers.some((provider) => provider.lifecycle_status === 'active') ? (
            <ModelForm
              key={editingModel?.id ?? 'new-model'}
              disabled={pending}
              editing={editingModel}
              modelCapabilities={runtime.model_capabilities}
              providers={runtime.providers}
              onCancel={() => setEditingModel(null)}
              onSubmit={async (payload) => {
                const saved = await mutate(
                  () => editingModel
                    ? updateModelConfiguration(editingModel.id, payload)
                    : createModelConfiguration(payload as ModelInput),
                  t('aiConfig.modelSaved'),
                );
                if (saved) setEditingModel(null);
                return saved;
              }}
            />
          ) : <section className="card"><p>{t('aiConfig.providerRequired')}</p></section>}
        <section className="table-card">
            <div className="section-header"><h2>{t('aiConfig.models')}</h2></div>
            <div className="model-provider-filters">
              <label className="model-provider-form-field" htmlFor="model-capability-filter">
                <span className="field-label">{t('aiConfig.capability')}</span>
                <select className="field-control" id="model-capability-filter" onChange={(event) => setCapabilityFilter(event.target.value)} value={capabilityFilter}>
                  <option value="">{t('aiConfig.all')}</option>
                  {capabilityOptions.map((item) => <option key={item} value={item}>{aiConfigurationLabel(item, t)}</option>)}
                </select>
              </label>
              <label className="model-provider-form-field" htmlFor="model-status-filter">
                <span className="field-label">{t('common.status')}</span>
                <select className="field-control" id="model-status-filter" onChange={(event) => setStatusFilter(event.target.value)} value={statusFilter}>
                  <option value="">{t('aiConfig.all')}</option>
                  {['available', 'disabled', 'provider_unavailable', 'never_validated', 'validation_stale', 'validation_failed', 'archived'].map((item) => <option key={item} value={item}>{aiConfigurationLabel(item, t)}</option>)}
                </select>
              </label>
            </div>
            {!filteredModels.length ? <p className="model-provider-empty-state">{t('aiConfig.noModels')}</p> : (
              <table>
                <thead><tr><th>{t('common.name')}</th><th>{t('aiConfig.provider')}</th><th>{t('aiConfig.capability')}</th><th>{t('common.status')}</th><th>{t('aiConfig.default')}</th><th>{t('aiConfig.lastValidation')}</th><th>{t('common.actionColumn')}</th></tr></thead>
                <tbody>
                  {filteredModels.map((model) => (
                    <tr key={model.id}>
                      <td>{model.display_name}<br /><small>{model.model_identifier}</small></td>
                      <td>{model.provider_display_name}</td>
                      <td>{aiConfigurationLabel(model.capability, t)}</td>
                      <td>
                        {aiConfigurationLabel(model.availability_status, t)}
                        {!model.available && model.runtime_actions.enable.reason ? (
                          <><br /><small>{aiConfigurationReason(model.runtime_actions.enable.reason_code, t)}</small></>
                        ) : null}
                      </td>
                      <td>
                        {model.is_default ? t('common.yes') : t('common.no')}
                        {model.is_default && !model.default_effective ? <><br /><small>{t('aiConfig.defaultInactive')}</small></> : null}
                      </td>
                      <td><EvidenceSummary evidence={model.latest_validation} /></td>
                      <td><div className="button-row">
                        {modelAdmin && model.lifecycle_status === 'active' ? <button className="button secondary" disabled={pending} onClick={() => setEditingModel(model)} type="button">{t('aiConfig.edit')}</button> : null}
                        {canValidate && model.lifecycle_status === 'active' ? <button className="button secondary" disabled={pending || !model.runtime_actions.validate.allowed} onClick={() => void mutate(() => validateModel(model.id), t('aiConfig.validationRecorded'))} title={model.runtime_actions.validate.reason_code ? aiConfigurationReason(model.runtime_actions.validate.reason_code, t) : undefined} type="button">{t('aiConfig.validate')}</button> : null}
                        {modelAdmin && model.lifecycle_status === 'active' ? model.enabled ? <button className="button danger administrative-destructive-action" disabled={pending || !model.runtime_actions.enable.allowed} onClick={() => setConfirmation({ title: t('confirmation.disableModelTitle', { name: model.display_name }), description: t('confirmation.disableModelEffect'), confirmLabel: t('aiConfig.disable'), action: () => mutate(() => setModelEnabled(model.id, false), t('aiConfig.modelSaved')) })} title={model.runtime_actions.enable.reason_code ? aiConfigurationReason(model.runtime_actions.enable.reason_code, t) : undefined} type="button">{t('aiConfig.disable')}</button> : <button className="button secondary" disabled={pending || !model.runtime_actions.enable.allowed} onClick={() => void mutate(() => setModelEnabled(model.id, true), t('aiConfig.modelSaved'))} title={model.runtime_actions.enable.reason_code ? aiConfigurationReason(model.runtime_actions.enable.reason_code, t) : undefined} type="button">{t('aiConfig.enable')}</button> : null}
                        {modelAdmin && model.lifecycle_status === 'active' ? <button className="button secondary" disabled={pending || !model.runtime_actions.set_default.allowed} onClick={() => void mutate(() => setDefaultModel(model.id, !model.is_default), t('aiConfig.defaultUpdated'))} title={model.runtime_actions.set_default.reason_code ? aiConfigurationReason(model.runtime_actions.set_default.reason_code, t) : undefined} type="button">{model.is_default ? t('aiConfig.unsetDefault') : t('aiConfig.setDefault')}</button> : null}
                        {modelAdmin ? model.lifecycle_status === 'active' ? <button className="button danger administrative-destructive-action" disabled={pending} onClick={() => setConfirmation({ title: t('confirmation.archiveModelTitle', { name: model.display_name }), description: t('confirmation.archiveModelEffect'), confirmLabel: t('aiConfig.archive'), action: () => mutate(() => setModelArchived(model.id, true), t('aiConfig.modelSaved')) })} type="button">{t('aiConfig.archive')}</button> : <button className="button secondary" disabled={pending} onClick={() => void mutate(() => setModelArchived(model.id, false), t('aiConfig.modelSaved'))} type="button">{t('aiConfig.restore')}</button> : null}
                      </div></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}
      <ActionConfirmationDialog cancelLabel={t('common.actions.cancel')} confirmLabel={confirmation?.confirmLabel ?? t('common.actions.confirm')} description={confirmation?.description ?? ''} onCancel={() => { if (!pending) setConfirmation(null); }} onConfirm={() => void runConfirmedAction()} open={Boolean(confirmation)} pending={pending} title={confirmation?.title ?? ''} />
    </div>
  );
}
