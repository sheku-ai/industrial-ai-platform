'use client';

import {
  useEffect,
  useMemo,
  useState,
  type FormEvent,
  type ReactNode,
} from 'react';

import { useI18n } from '../../i18n/I18nProvider';
import {
  createConnectorConfiguration,
  getConnectorWorkspaceRuntime,
  setConnectorConfigurationArchived,
  setConnectorConfigurationEnabled,
  updateConnectorConfiguration,
  type ConnectorCatalogType,
  type ConnectorConfiguration,
  type ConnectorConfigurationCreateInput,
  type ConnectorConfigurationField,
  type ConnectorConfigurationUpdateInput,
  type ConnectorWorkspaceRuntime,
} from '../../lib/connector-workspace-api';
import { PlatformApiError, type JsonObject } from '../../lib/platform-api';
import {
  localizedApiError,
  localizedStatusLabel,
} from '../../lib/presentation';

type EditorState =
  | { mode: 'create'; connector: null }
  | { mode: 'edit'; connector: ConnectorConfiguration };

type CredentialAction = 'clear' | 'keep' | 'none' | 'replace';

function asText(value: unknown, fallback = ''): string {
  if (value === null || value === undefined || value === '') return fallback;
  return String(value);
}

function asRecord(value: unknown): JsonObject {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as JsonObject
    : {};
}

function asList(value: unknown): JsonObject[] {
  return Array.isArray(value)
    ? value.filter((item): item is JsonObject => Boolean(
      item && typeof item === 'object' && !Array.isArray(item),
    ))
    : [];
}

function normalized(value: unknown): string {
  return asText(value).trim().toLowerCase();
}

function catalogLabel(value: unknown, fallback = ''): string {
  const text = asText(value, fallback).trim();
  return text.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ');
}

function isTechnicalSentinel(item: ConnectorCatalogType): boolean {
  return [item.code, item.connector_type_id].some(
    (value) => normalized(value) === 'disabled',
  );
}

function capabilityLabels(item: ConnectorCatalogType): string[] {
  const values = Array.isArray(item.runtime_capabilities)
    ? item.runtime_capabilities
    : [];
  return values
    .map((capability) => {
      if (typeof capability === 'string') return capability.trim();
      const record = asRecord(capability);
      return catalogLabel(record.label ?? record.name ?? record.code).trim();
    })
    .filter(Boolean);
}

function hasExecutableEvidence(item: ConnectorCatalogType): boolean {
  if (item.runtime_executable === true || item.executable === true) return true;
  return asList(item.runtime_capabilities).some(
    (capability) => capability.executable === true,
  );
}

function stateTone(value: unknown): 'ready' | 'attention' | 'neutral' {
  const state = normalized(value);
  if (
    ['blocked', 'error', 'failed', 'legacy_requires_review', 'unavailable']
      .includes(state)
  ) {
    return 'attention';
  }
  if (['available', 'verified'].includes(state)) return 'ready';
  return 'neutral';
}

function StatusBadge({
  value,
  label,
}: {
  value: unknown;
  label?: string;
}) {
  const { t } = useI18n();
  const tone = stateTone(value);
  return (
    <span className={`product-status product-status-${tone}`}>
      {label ?? localizedStatusLabel(value, t)}
    </span>
  );
}

function EmptyState({ children }: { children: ReactNode }) {
  return <div className="integration-empty-state">{children}</div>;
}

function CatalogSection({
  items,
  canAdminister,
  onCreate,
}: {
  items: ConnectorCatalogType[];
  canAdminister: boolean;
  onCreate: () => void;
}) {
  const { t } = useI18n();
  const configurableCount = items.filter((item) => item.configurable).length;

  if (items.length === 0) {
    return (
      <section
        className="table-card integration-section"
        aria-labelledby="integration-catalog-title"
      >
        <div className="integration-section-heading">
          <div>
            <h2 id="integration-catalog-title">{t('integrations.catalog.title')}</h2>
            <p>{t('integrations.catalog.help')}</p>
          </div>
        </div>
        <EmptyState>
          <strong>{t('integrations.catalog.emptyTitle')}</strong>
          <p>{t('integrations.catalog.emptyHelp')}</p>
        </EmptyState>
      </section>
    );
  }

  return (
    <section
      className="table-card integration-section"
      aria-labelledby="integration-catalog-title"
    >
      <div className="integration-section-heading">
        <div>
          <h2 id="integration-catalog-title">{t('integrations.catalog.title')}</h2>
          <p>{t('integrations.catalog.help')}</p>
        </div>
        <div className="integration-heading-actions">
          <StatusBadge
            value="available"
            label={t('integrations.catalog.authoritative')}
          />
          {canAdminister ? (
            <button
              className="button"
              type="button"
              disabled={configurableCount === 0}
              onClick={onCreate}
            >
              {t('integrations.configuration.add')}
            </button>
          ) : null}
        </div>
      </div>
      <div className="integration-catalog-grid">
        {items.map((item) => {
          const capabilities = capabilityLabels(item);
          const executable = hasExecutableEvidence(item);
          const description = asText(item.description);
          return (
            <article
              className="integration-catalog-card"
              key={item.connector_type_id}
            >
              <div className="integration-card-heading">
                <div>
                  <h3>{asText(item.name, t('integrations.catalog.unnamed'))}</h3>
                  {item.category ? <small>{catalogLabel(item.category)}</small> : null}
                </div>
                <StatusBadge
                  value={executable ? 'available' : 'configuration_only'}
                  label={t(executable
                    ? 'integrations.states.executable'
                    : 'integrations.states.configurationOnly')}
                />
              </div>
              {description
                ? <p>{description}</p>
                : <p>{t('integrations.catalog.noDescription')}</p>}
              <div
                className="integration-state-row"
                aria-label={t('integrations.catalog.catalogState')}
              >
                <span>{t('integrations.catalog.catalogState')}</span>
                <StatusBadge value={item.status} />
              </div>
              <div
                className="integration-state-row"
                aria-label={t('integrations.catalog.configurationState')}
              >
                <span>{t('integrations.catalog.configurationState')}</span>
                <StatusBadge
                  value={item.configurable ? 'available' : 'unavailable'}
                  label={t(item.configurable
                    ? 'integrations.catalog.configurationSupported'
                    : 'integrations.catalog.configurationUnavailable')}
                />
              </div>
              <div>
                <strong className="integration-subheading">
                  {t('integrations.catalog.capabilities')}
                </strong>
                {capabilities.length > 0 ? (
                  <ul className="integration-capability-list">
                    {capabilities.map((capability) => (
                      <li key={capability}>{capability}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="integration-muted">
                    {t('integrations.catalog.noCapabilities')}
                  </p>
                )}
              </div>
              {!executable ? (
                <p className="integration-notice">
                  {t('integrations.catalog.executionNotDeclared')}
                </p>
              ) : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}

function fieldValue(
  source: JsonObject,
  field: ConnectorConfigurationField,
): string | boolean {
  const value = source[field.key];
  if (field.type === 'boolean') return typeof value === 'boolean' ? value : '';
  return value === null || value === undefined ? '' : String(value);
}

function buildConfiguration(
  fields: ConnectorConfigurationField[],
  values: Record<string, string | boolean>,
): JsonObject {
  const configuration: JsonObject = {};
  for (const field of fields) {
    if (!field.editable) continue;
    const value = values[field.key];
    if (value === '' || value === undefined) continue;
    if (field.type === 'boolean') {
      configuration[field.key] = value === true || value === 'true';
    } else if (field.type === 'integer') {
      configuration[field.key] = Number.parseInt(String(value), 10);
    } else if (field.type === 'number') {
      configuration[field.key] = Number(String(value));
    } else {
      configuration[field.key] = String(value);
    }
  }
  return configuration;
}

function ConfigurationField({
  field,
  value,
  disabled,
  onChange,
}: {
  field: ConnectorConfigurationField;
  value: string | boolean;
  disabled: boolean;
  onChange: (value: string | boolean) => void;
}) {
  const { t } = useI18n();
  const id = `connector-configuration-${field.key}`;
  const helpId = `${id}-help`;
  const required = field.required && field.editable;
  const describedBy = field.description ? helpId : undefined;

  return (
    <div className="integration-form-field">
      <label className="field-label" htmlFor={id}>
        {field.label}
      </label>
      {field.options.length > 0 ? (
        <select
          className="field-control"
          id={id}
          value={String(value)}
          required={required}
          disabled={disabled || !field.editable}
          aria-describedby={describedBy}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="">{t('common.notSelected')}</option>
          {field.options.map((option) => (
            <option key={String(option)} value={String(option)}>
              {String(option)}
            </option>
          ))}
        </select>
      ) : field.type === 'boolean' ? (
        <select
          className="field-control"
          id={id}
          value={value === '' ? '' : String(value)}
          required={required}
          disabled={disabled || !field.editable}
          aria-describedby={describedBy}
          onChange={(event) => onChange(event.target.value)}
        >
          <option value="">{t('common.notSelected')}</option>
          <option value="true">{t('common.yes')}</option>
          <option value="false">{t('common.no')}</option>
        </select>
      ) : (
        <input
          className="field-control"
          id={id}
          type={field.type === 'integer' || field.type === 'number' ? 'number' : 'text'}
          step={field.type === 'integer' ? '1' : field.type === 'number' ? 'any' : undefined}
          value={String(value)}
          required={required}
          disabled={disabled || !field.editable}
          aria-describedby={describedBy}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
      {field.description ? (
        <p className="integration-field-help" id={helpId}>{field.description}</p>
      ) : null}
      {!field.editable ? (
        <p className="integration-field-help">
          {t('integrations.configuration.readOnlyField')}
        </p>
      ) : null}
    </div>
  );
}

function ConfigurationForm({
  editor,
  catalog,
  pending,
  error,
  onCancel,
  onSubmit,
}: {
  editor: EditorState;
  catalog: ConnectorCatalogType[];
  pending: boolean;
  error: string | null;
  onCancel: () => void;
  onSubmit: (
    payload: ConnectorConfigurationCreateInput | ConnectorConfigurationUpdateInput,
  ) => Promise<void>;
}) {
  const { t } = useI18n();
  const editing = editor.mode === 'edit' ? editor.connector : null;
  const [connectorTypeId, setConnectorTypeId] = useState(
    editing?.connector_type_id ?? '',
  );
  const [code, setCode] = useState(editing?.code ?? '');
  const [name, setName] = useState(editing?.name ?? '');
  const [values, setValues] = useState<Record<string, string | boolean>>({});
  const [credentialAction, setCredentialAction] = useState<CredentialAction>(
    editing ? 'keep' : 'none',
  );
  const [resolverType, setResolverType] = useState('');
  const [credentialReference, setCredentialReference] = useState('');
  const [credentialConfirmed, setCredentialConfirmed] = useState(false);
  const [clientError, setClientError] = useState<string | null>(null);

  const selectedType = catalog.find(
    (item) => item.connector_type_id === connectorTypeId,
  );
  const fields = useMemo(
    () => selectedType?.configuration_fields ?? [],
    [selectedType],
  );
  const credential = selectedType?.credential;
  const replacingCredential = credentialAction === 'replace';
  const clearingCredential = credentialAction === 'clear';

  useEffect(() => {
    const source = editing?.configuration ?? {};
    setValues(Object.fromEntries(
      fields.map((field) => [field.key, fieldValue(source, field)]),
    ));
    setResolverType('');
    setCredentialReference('');
    setCredentialConfirmed(false);
    setCredentialAction(editing ? 'keep' : 'none');
  }, [connectorTypeId, editing, fields]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setClientError(null);
    if (!selectedType) {
      setClientError(t('integrations.configuration.selectTypeError'));
      return;
    }
    if (!selectedType.configurable) {
      setClientError(t('integrations.configuration.typeUnavailableError'));
      return;
    }
    if (
      fields.some((field) => (
        field.required
        && field.editable
        && (values[field.key] === '' || values[field.key] === undefined)
      ))
    ) {
      setClientError(t('integrations.configuration.requiredFieldsError'));
      return;
    }
    if (
      credential?.required
      && credentialAction !== 'replace'
      && !editing?.credential_configured
    ) {
      setClientError(t('integrations.configuration.credentialRequiredError'));
      return;
    }
    if (
      replacingCredential
      && (!resolverType || !credentialReference.trim())
    ) {
      setClientError(t('integrations.configuration.credentialValuesError'));
      return;
    }
    if (
      editing
      && (replacingCredential || clearingCredential)
      && !credentialConfirmed
    ) {
      setClientError(t('integrations.configuration.credentialConfirmError'));
      return;
    }

    const configuration = buildConfiguration(fields, values);
    if (editing) {
      const payload: ConnectorConfigurationUpdateInput = {
        expected_version: editing.configuration_version,
        name: name.trim(),
        configuration,
      };
      if (replacingCredential) {
        payload.credential = {
          resolver_type: resolverType,
          reference: credentialReference.trim(),
        };
      } else if (clearingCredential) {
        payload.clear_credential = true;
      }
      await onSubmit(payload);
      return;
    }

    const payload: ConnectorConfigurationCreateInput = {
      connector_type_id: selectedType.connector_type_id,
      code: code.trim().toLowerCase(),
      name: name.trim(),
      configuration,
    };
    if (replacingCredential) {
      payload.credential = {
        resolver_type: resolverType,
        reference: credentialReference.trim(),
      };
    }
    await onSubmit(payload);
  }

  return (
    <section
      className="table-card integration-section integration-configuration-editor"
      aria-labelledby="integration-configuration-form-title"
    >
      <div className="integration-section-heading">
        <div>
          <h2 id="integration-configuration-form-title">
            {t(editing
              ? 'integrations.configuration.editTitle'
              : 'integrations.configuration.createTitle')}
          </h2>
          <p>{t('integrations.configuration.formHelp')}</p>
        </div>
      </div>
      <form className="integration-form" onSubmit={(event) => void submit(event)}>
        <div className="integration-form-grid">
          <div className="integration-form-field">
            <label className="field-label" htmlFor="connector-type">
              {t('integrations.configuration.type')}
            </label>
            <select
              className="field-control"
              id="connector-type"
              value={connectorTypeId}
              required
              disabled={pending || Boolean(editing)}
              aria-describedby="connector-type-help"
              onChange={(event) => setConnectorTypeId(event.target.value)}
            >
              <option value="">{t('integrations.configuration.selectType')}</option>
              {catalog.filter((item) => item.configurable).map((item) => (
                <option key={item.connector_type_id} value={item.connector_type_id}>
                  {item.name}
                </option>
              ))}
            </select>
            <p className="integration-field-help" id="connector-type-help">
              {t('integrations.configuration.typeHelp')}
            </p>
          </div>

          <div className="integration-form-field">
            <label className="field-label" htmlFor="connector-code">
              {t('integrations.configuration.code')}
            </label>
            <input
              className="field-control"
              id="connector-code"
              value={code}
              required
              minLength={1}
              maxLength={128}
              pattern="[a-z0-9][a-z0-9._-]*"
              disabled={pending || Boolean(editing)}
              aria-describedby="connector-code-help"
              onChange={(event) => setCode(event.target.value)}
            />
            <p className="integration-field-help" id="connector-code-help">
              {t(editing
                ? 'integrations.configuration.codeImmutableHelp'
                : 'integrations.configuration.codeHelp')}
            </p>
          </div>

          <div className="integration-form-field">
            <label className="field-label" htmlFor="connector-name">
              {t('common.name')}
            </label>
            <input
              className="field-control"
              id="connector-name"
              value={name}
              required
              minLength={1}
              maxLength={255}
              disabled={pending}
              aria-describedby="connector-name-help"
              onChange={(event) => setName(event.target.value)}
            />
            <p className="integration-field-help" id="connector-name-help">
              {t('integrations.configuration.nameHelp')}
            </p>
          </div>

          {fields.map((field) => (
            <ConfigurationField
              key={field.key}
              field={field}
              value={values[field.key] ?? ''}
              disabled={pending}
              onChange={(value) => setValues((current) => ({
                ...current,
                [field.key]: value,
              }))}
            />
          ))}
        </div>

        {credential?.supported ? (
          <fieldset className="integration-credential-fieldset" disabled={pending}>
            <legend>{t('integrations.configuration.credentialTitle')}</legend>
            <p className="integration-field-help">
              {t('integrations.configuration.credentialOpaqueHelp')}
            </p>
            {editing?.credential_configured ? (
              <p className="integration-credential-state">
                {t('integrations.configuration.credentialConfigured')}
              </p>
            ) : null}
            <div className="integration-credential-actions">
              {editing ? (
                <label>
                  <input
                    type="radio"
                    name="credential-action"
                    value="keep"
                    checked={credentialAction === 'keep'}
                    onChange={() => setCredentialAction('keep')}
                  />
                  {t('integrations.configuration.credentialKeep')}
                </label>
              ) : (
                <label>
                  <input
                    type="radio"
                    name="credential-action"
                    value="none"
                    checked={credentialAction === 'none'}
                    disabled={credential.required}
                    onChange={() => setCredentialAction('none')}
                  />
                  {t('integrations.configuration.credentialNone')}
                </label>
              )}
              <label>
                <input
                  type="radio"
                  name="credential-action"
                  value="replace"
                  checked={credentialAction === 'replace'}
                  onChange={() => {
                    setCredentialAction('replace');
                    setCredentialConfirmed(false);
                  }}
                />
                {t(editing
                  ? 'integrations.configuration.credentialReplace'
                  : 'integrations.configuration.credentialAdd')}
              </label>
              {editing && !credential.required && editing.credential_configured ? (
                <label>
                  <input
                    type="radio"
                    name="credential-action"
                    value="clear"
                    checked={credentialAction === 'clear'}
                    onChange={() => {
                      setCredentialAction('clear');
                      setCredentialConfirmed(false);
                    }}
                  />
                  {t('integrations.configuration.credentialRemove')}
                </label>
              ) : null}
            </div>

            {replacingCredential ? (
              <div className="integration-form-grid integration-credential-inputs">
                <div className="integration-form-field">
                  <label className="field-label" htmlFor="credential-resolver">
                    {t('integrations.configuration.credentialResolver')}
                  </label>
                  <select
                    className="field-control"
                    id="credential-resolver"
                    value={resolverType}
                    required
                    aria-describedby="credential-resolver-help"
                    onChange={(event) => setResolverType(event.target.value)}
                  >
                    <option value="">{t('common.notSelected')}</option>
                    {credential.resolver_types.map((resolver) => (
                      <option key={resolver} value={resolver}>{resolver}</option>
                    ))}
                  </select>
                  <p className="integration-field-help" id="credential-resolver-help">
                    {t('integrations.configuration.credentialResolverHelp')}
                  </p>
                </div>
                <div className="integration-form-field">
                  <label className="field-label" htmlFor="credential-reference">
                    {t('integrations.configuration.credentialReference')}
                  </label>
                  <input
                    className="field-control"
                    id="credential-reference"
                    value={credentialReference}
                    required
                    maxLength={1024}
                    autoComplete="off"
                    aria-describedby="credential-reference-help"
                    onChange={(event) => setCredentialReference(event.target.value)}
                  />
                  <p className="integration-field-help" id="credential-reference-help">
                    {t('integrations.configuration.credentialReferenceHelp')}
                  </p>
                </div>
              </div>
            ) : null}

            {editing && (replacingCredential || clearingCredential) ? (
              <label className="integration-credential-confirm">
                <input
                  type="checkbox"
                  checked={credentialConfirmed}
                  onChange={(event) => setCredentialConfirmed(event.target.checked)}
                />
                {t(replacingCredential
                  ? 'integrations.configuration.credentialReplaceConfirm'
                  : 'integrations.configuration.credentialRemoveConfirm')}
              </label>
            ) : null}
          </fieldset>
        ) : (
          <aside className="integration-notice">
            {t('integrations.configuration.credentialUnsupported')}
          </aside>
        )}

        {clientError || error ? (
          <p className="form-error" role="alert">{clientError ?? error}</p>
        ) : null}
        <div className="integration-form-actions">
          <button className="button" type="submit" disabled={pending}>
            {pending
              ? t('integrations.configuration.saving')
              : t('common.actions.save')}
          </button>
          <button
            className="button secondary"
            type="button"
            disabled={pending}
            onClick={onCancel}
          >
            {t('common.actions.cancel')}
          </button>
        </div>
      </form>
    </section>
  );
}

function ConnectionsSection({
  catalog,
  connectors,
  canAdminister,
  pendingAction,
  operationError,
  operationSuccess,
  onEdit,
  onToggleEnabled,
  onToggleArchived,
}: {
  catalog: ConnectorCatalogType[];
  connectors: ConnectorConfiguration[];
  canAdminister: boolean;
  pendingAction: string | null;
  operationError: string | null;
  operationSuccess: string | null;
  onEdit: (connector: ConnectorConfiguration) => void;
  onToggleEnabled: (connector: ConnectorConfiguration) => void;
  onToggleArchived: (connector: ConnectorConfiguration) => void;
}) {
  const { t, date } = useI18n();
  const catalogById = useMemo(
    () => new Map(catalog.map((item) => [item.connector_type_id, item])),
    [catalog],
  );

  return (
    <section
      className="table-card integration-section"
      aria-labelledby="integration-connections-title"
    >
      <div className="integration-section-heading">
        <div>
          <h2 id="integration-connections-title">
            {t('integrations.connections.title')}
          </h2>
          <p>{t('integrations.connections.help')}</p>
        </div>
      </div>

      <aside
        className="integration-notice"
        aria-label={t('integrations.configuration.title')}
      >
        <strong>{t('integrations.configuration.title')}</strong>
        <p>{t(canAdminister
          ? 'integrations.configuration.adminHelp'
          : 'integrations.configuration.readOnlyHelp')}</p>
        <p>{t('integrations.configuration.credentialsHelp')}</p>
      </aside>

      {operationError ? (
        <p className="form-error" role="alert">{operationError}</p>
      ) : null}
      {operationSuccess ? (
        <p className="success-message" role="status">{operationSuccess}</p>
      ) : null}

      {connectors.length === 0 ? (
        <EmptyState>
          <strong>{t('integrations.connections.emptyTitle')}</strong>
          <p>{t('integrations.connections.emptyHelp')}</p>
        </EmptyState>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>{t('common.name')}</th>
                <th>{t('integrations.connections.catalogType')}</th>
                <th>{t('integrations.connections.lifecycle')}</th>
                <th>{t('integrations.connections.configuration')}</th>
                <th>{t('common.enabled')}</th>
                <th>{t('integrations.connections.execution')}</th>
                <th>{t('integrations.connections.verification')}</th>
                <th>{t('integrations.connections.credential')}</th>
                <th>{t('integrations.connections.lastEvidence')}</th>
                {canAdminister ? <th>{t('common.actionColumn')}</th> : null}
              </tr>
            </thead>
            <tbody>
              {connectors.map((connector) => {
                const type = catalogById.get(connector.connector_type_id);
                const executable = type ? hasExecutableEvidence(type) : false;
                const archived = connector.status === 'archived';
                const busy = pendingAction === connector.connector_id;
                const actionLocked = pendingAction !== null;
                const legacy = connector.configuration_validation_status
                  === 'legacy_requires_review';
                return (
                  <tr key={connector.connector_id}>
                    <td>
                      <strong>
                        {asText(
                          connector.name,
                          t('integrations.connections.unnamed'),
                        )}
                      </strong>
                      <small className="table-secondary">{connector.code}</small>
                    </td>
                    <td>{type?.name ?? t('common.notAvailable')}</td>
                    <td><StatusBadge value={connector.status} /></td>
                    <td>
                      <StatusBadge
                        value={legacy
                          ? 'legacy_requires_review'
                          : connector.configuration_status}
                        label={legacy
                          ? t('integrations.configuration.legacyRequiresReview')
                          : undefined}
                      />
                    </td>
                    <td>
                      <StatusBadge
                        value={connector.enabled ? 'enabled' : 'disabled'}
                      />
                    </td>
                    <td>
                      <StatusBadge
                        value={executable ? 'available' : 'configuration_only'}
                        label={t(executable
                          ? 'integrations.states.executable'
                          : 'integrations.states.configurationOnly')}
                      />
                    </td>
                    <td><StatusBadge value="unverified" /></td>
                    <td>
                      {connector.credential_configured
                        ? t('integrations.configuration.credentialConfigured')
                        : t('integrations.configuration.credentialNotConfigured')}
                    </td>
                    <td>
                      {connector.last_run_at
                        ? date(String(connector.last_run_at), {
                          dateStyle: 'medium',
                          timeStyle: 'short',
                        })
                        : t('integrations.connections.noRuntimeEvidence')}
                    </td>
                    {canAdminister ? (
                      <td>
                        <div className="integration-row-actions">
                          <button
                            className="button secondary"
                            type="button"
                            disabled={actionLocked || archived || !type?.configurable}
                            onClick={() => onEdit(connector)}
                          >
                            {t('integrations.configuration.edit')}
                          </button>
                          <button
                            className="button secondary"
                            type="button"
                            disabled={actionLocked || archived || legacy || !type?.configurable}
                            onClick={() => onToggleEnabled(connector)}
                          >
                            {busy
                              ? t('integrations.configuration.updating')
                              : t(connector.enabled
                                ? 'integrations.configuration.disable'
                                : 'integrations.configuration.enable')}
                          </button>
                          <button
                            className="button secondary"
                            type="button"
                            disabled={actionLocked}
                            onClick={() => onToggleArchived(connector)}
                          >
                            {t(archived
                              ? 'integrations.configuration.restore'
                              : 'integrations.configuration.archive')}
                          </button>
                        </div>
                      </td>
                    ) : null}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function SourceImportSection() {
  const { t } = useI18n();
  return (
    <section
      className="table-card integration-section"
      aria-labelledby="integration-import-title"
    >
      <div className="integration-section-heading">
        <div>
          <h2 id="integration-import-title">{t('integrations.import.title')}</h2>
          <p>{t('integrations.import.help')}</p>
        </div>
        <StatusBadge value="unavailable" />
      </div>
      <div className="integration-empty-state">
        <strong>{t('integrations.import.unavailableTitle')}</strong>
        <p>{t('integrations.import.unavailableHelp')}</p>
        <button className="button secondary" type="button" disabled>
          {t('integrations.import.action')}
        </button>
      </div>
    </section>
  );
}

function OptionalDependencies({ runtime }: { runtime: ConnectorWorkspaceRuntime }) {
  const { t } = useI18n();
  const items = [
    {
      title: t('integrations.optional.securityTitle'),
      status: 'not_evaluated',
      label: t('integrations.optional.accessEnforced'),
      description: t('integrations.optional.securityHelp'),
    },
    {
      title: t('integrations.optional.providersTitle'),
      status: runtime.external_calls_performed ? 'active' : 'not_evaluated',
      label: t(runtime.external_calls_performed
        ? 'integrations.optional.providersUsedLabel'
        : 'integrations.optional.providersNotUsedLabel'),
      description: runtime.external_calls_performed
        ? t('integrations.optional.providersUsed')
        : t('integrations.optional.providersNotUsed'),
    },
    {
      title: t('integrations.optional.aiTitle'),
      status: runtime.llm_used ? 'active' : 'not_evaluated',
      label: t(runtime.llm_used
        ? 'integrations.optional.usedInRead'
        : 'integrations.optional.notUsedInRead'),
      description: runtime.llm_used
        ? t('integrations.optional.aiUsed')
        : t('integrations.optional.aiNotUsed'),
    },
    {
      title: t('integrations.optional.vectorTitle'),
      status: runtime.qdrant_used ? 'active' : 'not_evaluated',
      label: t(runtime.qdrant_used
        ? 'integrations.optional.usedInRead'
        : 'integrations.optional.notUsedInRead'),
      description: runtime.qdrant_used
        ? t('integrations.optional.vectorUsed')
        : t('integrations.optional.vectorNotUsed'),
    },
  ];

  return (
    <section
      className="table-card integration-section"
      aria-labelledby="integration-optional-title"
    >
      <div className="integration-section-heading">
        <div>
          <h2 id="integration-optional-title">{t('integrations.optional.title')}</h2>
          <p>{t('integrations.optional.help')}</p>
        </div>
      </div>
      <div className="integration-dependency-grid">
        {items.map((item) => (
          <article className="context-card" key={item.title}>
            <div className="integration-card-heading">
              <h3>{item.title}</h3>
              <StatusBadge value={item.status} label={item.label} />
            </div>
            <p>{item.description}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function RuntimeEvidence({
  runtime,
  connectors,
}: {
  runtime: ConnectorWorkspaceRuntime;
  connectors: ConnectorConfiguration[];
}) {
  const { t, date, number } = useI18n();
  const runs = asRecord(runtime.connector_runs);
  const recentRuns = asList(runs.recent_runs);
  const impact = asRecord(runtime.sync_ingestion_impact);
  const audit = asRecord(runtime.audit_trace);
  const diagnostics = asRecord(runtime.diagnostics);
  const connectorNames = new Map(
    connectors.map((item) => [item.connector_id, item.name]),
  );
  const diagnosticCounts = [
    ['integrations.diagnostics.blocking', asList(diagnostics.blocking_issues).length],
    ['integrations.diagnostics.warnings', asList(diagnostics.warnings).length],
    ['integrations.diagnostics.pending', asList(diagnostics.pending_capabilities).length],
    ['integrations.diagnostics.degraded', asList(diagnostics.degraded_items).length],
  ] as const;

  return (
    <details className="advanced-panel">
      <summary>{t('integrations.evidence.title')}</summary>
      <div className="advanced-panel-content">
        <p className="integration-muted">{t('integrations.evidence.help')}</p>
        <section aria-labelledby="integration-runs-title">
          <h3 id="integration-runs-title">{t('integrations.evidence.runsTitle')}</h3>
          {recentRuns.length === 0 ? (
            <EmptyState><p>{t('integrations.evidence.noRuns')}</p></EmptyState>
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>{t('integrations.connections.title')}</th>
                    <th>{t('common.status')}</th>
                    <th>{t('integrations.evidence.started')}</th>
                    <th>{t('integrations.evidence.finished')}</th>
                    <th>{t('integrations.evidence.records')}</th>
                  </tr>
                </thead>
                <tbody>
                  {recentRuns.map((run) => (
                    <tr key={asText(run.connector_run_id)}>
                      <td>
                        {connectorNames.get(asText(run.connector_id))
                          || t('common.notAvailable')}
                      </td>
                      <td><StatusBadge value={run.status} /></td>
                      <td>
                        {run.started_at
                          ? date(String(run.started_at), {
                            dateStyle: 'medium',
                            timeStyle: 'short',
                          })
                          : t('common.notAvailable')}
                      </td>
                      <td>
                        {run.finished_at
                          ? date(String(run.finished_at), {
                            dateStyle: 'medium',
                            timeStyle: 'short',
                          })
                          : t('common.notAvailable')}
                      </td>
                      <td>{number(Number(run.records_processed ?? 0))}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
        <section aria-labelledby="integration-impact-title">
          <h3 id="integration-impact-title">{t('integrations.evidence.impactTitle')}</h3>
          <p className="integration-muted">{t('integrations.evidence.impactHelp')}</p>
          <div className="integration-metric-grid">
            <article>
              <small>{t('integrations.evidence.documentsCreated')}</small>
              <strong>{number(Number(impact.documents_created ?? 0))}</strong>
            </article>
            <article>
              <small>{t('integrations.evidence.documentsUpdated')}</small>
              <strong>{number(Number(impact.documents_updated ?? 0))}</strong>
            </article>
            <article>
              <small>{t('integrations.evidence.knowledgePublications')}</small>
              <strong>
                {number(Number(impact.knowledge_publications_triggered ?? 0))}
              </strong>
            </article>
            <article>
              <small>{t('integrations.evidence.indexUpdates')}</small>
              <strong>{number(Number(impact.index_updates_triggered ?? 0))}</strong>
            </article>
          </div>
        </section>
        <section aria-labelledby="integration-diagnostics-title">
          <h3 id="integration-diagnostics-title">
            {t('integrations.diagnostics.title')}
          </h3>
          <div className="integration-metric-grid">
            {diagnosticCounts.map(([key, count]) => (
              <article key={key}>
                <small>{t(key)}</small>
                <strong>{number(count)}</strong>
              </article>
            ))}
            <article>
              <small>{t('integrations.evidence.auditEvents')}</small>
              <strong>{number(Number(audit.audit_events_count ?? 0))}</strong>
            </article>
          </div>
          <p className="integration-muted">
            {t('integrations.diagnostics.safeHelp')}
          </p>
        </section>
      </div>
    </details>
  );
}

export function ConnectorWorkspace() {
  const { t, number } = useI18n();
  const [runtime, setRuntime] = useState<ConnectorWorkspaceRuntime | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [mutationPending, setMutationPending] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const [operationError, setOperationError] = useState<string | null>(null);
  const [operationSuccess, setOperationSuccess] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      setErrorStatus(null);
      try {
        const payload = await getConnectorWorkspaceRuntime();
        if (!cancelled) setRuntime(payload);
      } catch (cause) {
        if (!cancelled) {
          setRuntime(null);
          setErrorStatus(cause instanceof PlatformApiError ? cause.status : null);
          setError(cause instanceof PlatformApiError && [400, 422].includes(cause.status)
            ? t('integrations.errors.selectOrganization')
            : localizedApiError(cause, t, 'integrations.errors.unavailable'));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [reloadToken, t]);

  const catalog = useMemo(
    () => (runtime?.connector_types ?? []).filter(
      (item) => !isTechnicalSentinel(item),
    ),
    [runtime?.connector_types],
  );

  async function submitConfiguration(
    payload: ConnectorConfigurationCreateInput | ConnectorConfigurationUpdateInput,
  ) {
    if (!editor) return;
    setMutationPending(true);
    setMutationError(null);
    setOperationSuccess(null);
    try {
      if (editor.mode === 'create') {
        await createConnectorConfiguration(
          payload as ConnectorConfigurationCreateInput,
        );
        setOperationSuccess(t('integrations.configuration.created'));
      } else {
        await updateConnectorConfiguration(
          editor.connector.connector_id,
          payload as ConnectorConfigurationUpdateInput,
        );
        setOperationSuccess(t('integrations.configuration.updated'));
      }
      setEditor(null);
      setReloadToken((value) => value + 1);
    } catch (cause) {
      setMutationError(localizedApiError(
        cause,
        t,
        'integrations.configuration.operationFailed',
      ));
    } finally {
      setMutationPending(false);
    }
  }

  async function toggleEnabled(connector: ConnectorConfiguration) {
    setPendingAction(connector.connector_id);
    setOperationError(null);
    setOperationSuccess(null);
    try {
      await setConnectorConfigurationEnabled(
        connector.connector_id,
        !connector.enabled,
        connector.configuration_version,
      );
      setOperationSuccess(t(connector.enabled
        ? 'integrations.configuration.disabled'
        : 'integrations.configuration.enabled'));
      setReloadToken((value) => value + 1);
    } catch (cause) {
      setOperationError(localizedApiError(
        cause,
        t,
        'integrations.configuration.operationFailed',
      ));
    } finally {
      setPendingAction(null);
    }
  }

  async function toggleArchived(connector: ConnectorConfiguration) {
    const archived = connector.status === 'archived';
    const confirmed = window.confirm(t(archived
      ? 'integrations.configuration.restoreConfirm'
      : 'integrations.configuration.archiveConfirm'));
    if (!confirmed) return;
    setPendingAction(connector.connector_id);
    setOperationError(null);
    setOperationSuccess(null);
    try {
      await setConnectorConfigurationArchived(
        connector.connector_id,
        !archived,
        connector.configuration_version,
      );
      setOperationSuccess(t(archived
        ? 'integrations.configuration.restored'
        : 'integrations.configuration.archived'));
      if (editor?.mode === 'edit'
        && editor.connector.connector_id === connector.connector_id) {
        setEditor(null);
      }
      setReloadToken((value) => value + 1);
    } catch (cause) {
      setOperationError(localizedApiError(
        cause,
        t,
        'integrations.configuration.operationFailed',
      ));
    } finally {
      setPendingAction(null);
    }
  }

  if (loading) {
    return (
      <section
        className="card integration-state-panel"
        role="status"
        aria-live="polite"
      >
        <h2>{t('integrations.loading.title')}</h2>
        <p>{t('integrations.loading.help')}</p>
      </section>
    );
  }

  if (error || !runtime) {
    const forbidden = errorStatus === 403;
    const unauthorized = errorStatus === 401;
    return (
      <section className="card integration-state-panel" role="alert">
        <h2>
          {t(forbidden
            ? 'integrations.errors.forbiddenTitle'
            : 'integrations.errors.title')}
        </h2>
        <p>{error ?? t('integrations.errors.unavailable')}</p>
        {forbidden ? (
          <a className="text-link" href="/security">
            {t('integrations.errors.reviewAccess')}
          </a>
        ) : null}
        {!forbidden && !unauthorized ? (
          <button
            className="button secondary"
            type="button"
            onClick={() => setReloadToken((value) => value + 1)}
          >
            {t('common.actions.retry')}
          </button>
        ) : null}
      </section>
    );
  }

  const canAdminister = runtime.capabilities.administer === true;
  const executableTypes = catalog.filter(hasExecutableEvidence).length;
  const enabledConnectors = runtime.connectors.filter(
    (item) => item.enabled,
  ).length;

  return (
    <div
      className="platform-home integration-workspace"
      data-connector-workspace="ready"
    >
      <header className="platform-hero integration-hero">
        <div>
          <span className="badge">{t('integrations.hero.eyebrow')}</span>
          <h2>{t('integrations.hero.title')}</h2>
          <p>{t('integrations.hero.help')}</p>
        </div>
        <div className="integration-hero-actions">
          <p>{t(canAdminister
            ? 'integrations.hero.admin'
            : 'integrations.hero.readOnly')}</p>
          <button
            className="button secondary"
            type="button"
            disabled={loading || mutationPending || pendingAction !== null}
            aria-busy={loading}
            onClick={() => setReloadToken((value) => value + 1)}
          >
            {t('common.actions.refresh')}
          </button>
        </div>
      </header>

      <section
        className="workspace-summary-strip"
        aria-label={t('integrations.summary.title')}
      >
        <div>
          <small>{t('integrations.summary.catalog')}</small>
          <strong>{number(catalog.length)}</strong>
        </div>
        <div>
          <small>{t('integrations.summary.configurations')}</small>
          <strong>{number(runtime.connectors.length)}</strong>
        </div>
        <div>
          <small>{t('integrations.summary.enabled')}</small>
          <strong>{number(enabledConnectors)}</strong>
        </div>
        <div>
          <small>{t('integrations.summary.executable')}</small>
          <strong>{number(executableTypes)}</strong>
        </div>
      </section>

      <CatalogSection
        items={catalog}
        canAdminister={canAdminister}
        onCreate={() => {
          setMutationError(null);
          setEditor({ mode: 'create', connector: null });
        }}
      />
      {editor ? (
        <ConfigurationForm
          key={editor.mode === 'edit'
            ? `edit-${editor.connector.connector_id}`
            : 'create'}
          editor={editor}
          catalog={catalog}
          pending={mutationPending}
          error={mutationError}
          onCancel={() => {
            setEditor(null);
            setMutationError(null);
          }}
          onSubmit={submitConfiguration}
        />
      ) : null}
      <ConnectionsSection
        catalog={catalog}
        connectors={runtime.connectors}
        canAdminister={canAdminister}
        pendingAction={pendingAction}
        operationError={operationError}
        operationSuccess={operationSuccess}
        onEdit={(connector) => {
          setMutationError(null);
          setEditor({ mode: 'edit', connector });
        }}
        onToggleEnabled={(connector) => void toggleEnabled(connector)}
        onToggleArchived={(connector) => void toggleArchived(connector)}
      />
      <SourceImportSection />
      <OptionalDependencies runtime={runtime} />
      <RuntimeEvidence runtime={runtime} connectors={runtime.connectors} />
    </div>
  );
}
