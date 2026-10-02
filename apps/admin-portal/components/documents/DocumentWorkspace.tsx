'use client';

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
} from 'react';

import { useI18n } from '../../i18n/I18nProvider';
import {
  getDocumentOrganizationAssociations,
  getDocumentWorkspaceRuntime,
  listDocumentTypes,
  orchestrateDocumentLifecycle,
  saveDocumentOrganizationAssociations,
  type DocumentConfigurationOption,
  type DocumentOrganizationAssociationRuntime,
  type DocumentOrganizationStructureOption,
  type DocumentRegistryItem,
  type DocumentWorkspaceRuntime,
  type DocumentWorkspaceVersion,
} from '../../lib/document-workspace-api';
import { PlatformApiError } from '../../lib/platform-api';
import {
  issueMessage,
  localizedApiError,
  localizedProductLabel,
  localizedStatusLabel,
  productStatus,
} from '../../lib/presentation';
import { LocalizedDate, LocalizedText } from '../layout/LocalizedText';
import { useOrganization } from '../organization/OrganizationContext';

const STRUCTURE_NODE_TYPE_KEYS: Record<string, string> = {
  structure_root: 'structureWorkspace.nodeTypes.structureRoot.name',
  structure_group: 'structureWorkspace.nodeTypes.structureGroup.name',
  structure_node: 'structureWorkspace.nodeTypes.structureNode.name',
};

function localizedStructureNodeType(nodeType: string, t: (key: string) => string): string {
  const key = STRUCTURE_NODE_TYPE_KEYS[nodeType];
  return key ? t(key) : t('structureWorkspace.unknownType');
}

function structureNodeName(name: string, t: (key: string) => string): string {
  return name.trim() || t('structureWorkspace.unnamedNode');
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function booleanValue(value: unknown): boolean {
  return value === true
    || ['ready', 'completed', 'published', 'indexed', 'searchable']
      .includes(String(value ?? '').toLowerCase());
}

function documentStage(document: DocumentRegistryItem): string {
  const readiness = record(document.readiness);
  if (['failed', 'error', 'blocked'].includes(document.status.toLowerCase())) return 'failed';
  if (booleanValue(readiness.search_ready) || booleanValue(readiness.indexed)) return 'indexed';
  if (booleanValue(readiness.knowledge_ready) || booleanValue(readiness.published)) return 'published';
  if (booleanValue(readiness.processing_ready) || booleanValue(readiness.processed)) return 'processed';
  return document.status || 'registered';
}

function StatusPill({ value }: { value: unknown }) {
  const { t } = useI18n();
  return (
    <span className={`product-status product-status-${productStatus(value)}`}>
      {localizedStatusLabel(value, t)}
    </span>
  );
}

function bytesToBase64(bytes: Uint8Array): string {
  const chunkSize = 0x8000;
  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
  }
  return window.btoa(binary);
}

async function fileDescriptor(file: File): Promise<{ bytes: string; checksum: string }> {
  const buffer = await file.arrayBuffer();
  const digest = await window.crypto.subtle.digest('SHA-256', buffer);
  const checksum = Array.from(new Uint8Array(digest))
    .map((value) => value.toString(16).padStart(2, '0'))
    .join('');
  return { bytes: bytesToBase64(new Uint8Array(buffer)), checksum };
}

function orderedStructure(
  options: DocumentOrganizationStructureOption[],
): Array<{ item: DocumentOrganizationStructureOption; depth: number }> {
  const byId = new Map(options.map((item) => [item.id, item]));
  const byParent = new Map<string, DocumentOrganizationStructureOption[]>();
  const sortNodes = (items: DocumentOrganizationStructureOption[]) => (
    [...items].sort((left, right) => (
      left.name.localeCompare(right.name) || left.code.localeCompare(right.code)
    ))
  );
  for (const item of options) {
    if (item.parent_node_id && byId.has(item.parent_node_id) && item.parent_node_id !== item.id) {
      byParent.set(
        item.parent_node_id,
        [...(byParent.get(item.parent_node_id) ?? []), item],
      );
    }
  }
  const roots = sortNodes(options.filter(
    (item) => !item.parent_node_id
      || !byId.has(item.parent_node_id)
      || item.parent_node_id === item.id,
  ));
  const ordered: Array<{ item: DocumentOrganizationStructureOption; depth: number }> = [];
  const visited = new Set<string>();
  const visit = (item: DocumentOrganizationStructureOption, depth: number) => {
    if (visited.has(item.id)) return;
    visited.add(item.id);
    ordered.push({ item, depth });
    for (const child of sortNodes(byParent.get(item.id) ?? [])) visit(child, depth + 1);
  };
  for (const root of roots) visit(root, 0);
  for (const remaining of sortNodes(options.filter((item) => !visited.has(item.id)))) {
    visit(remaining, 0);
  }
  return ordered;
}

function OrganizationStructureSelector({
  idPrefix,
  options,
  selected,
  disabled,
  maxSelections,
  onToggle,
}: {
  idPrefix: string;
  options: DocumentOrganizationStructureOption[];
  selected: ReadonlySet<string>;
  disabled: boolean;
  maxSelections: number;
  onToggle: (nodeId: string, checked: boolean) => void;
}) {
  const { t } = useI18n();
  const [query, setQuery] = useState('');
  const byId = useMemo(
    () => new Map(options.map((item) => [item.id, item])),
    [options],
  );
  const ordered = useMemo(
    () => orderedStructure(options)
      .filter(({ item }) => {
        const normalized = query.trim().toLocaleLowerCase();
        return !normalized
          || item.name.toLocaleLowerCase().includes(normalized)
          || item.code.toLocaleLowerCase().includes(normalized);
      }),
    [options, query],
  );

  return (
    <div className="document-structure-selector">
      <label className="field-label" htmlFor={`${idPrefix}-search`}>
        {t('documentAssociations.searchLabel')}
      </label>
      <input
        className="field-control"
        disabled={disabled || options.length === 0}
        id={`${idPrefix}-search`}
        onChange={(event) => setQuery(event.target.value)}
        placeholder={t('documentAssociations.searchPlaceholder')}
        type="search"
        value={query}
      />
      {options.length === 0 ? (
        <div className="document-structure-empty">
          <strong>{t('documentAssociations.emptyStructureTitle')}</strong>
          <p>{t('documentAssociations.emptyStructureHelp')}</p>
        </div>
      ) : ordered.length === 0 ? (
        <div className="document-structure-empty">
          <strong>{t('documentAssociations.noMatches')}</strong>
        </div>
      ) : (
        <div
          aria-label={t('documentAssociations.selectorLabel')}
          className="document-structure-options"
          role="group"
        >
          {ordered.map(({ item, depth }) => {
            const checked = selected.has(item.id);
            const inputDisabled = disabled
              || (!checked && (!item.selectable || selected.size >= maxSelections));
            return (
              <label
                className={`document-structure-option${checked ? ' is-selected' : ''}${item.selectable ? '' : ' is-unavailable'}`}
                htmlFor={`${idPrefix}-${item.id}`}
                key={item.id}
                style={{ '--structure-depth': depth } as CSSProperties}
              >
                <input
                  checked={checked}
                  disabled={inputDisabled}
                  id={`${idPrefix}-${item.id}`}
                  onChange={(event) => onToggle(item.id, event.target.checked)}
                  type="checkbox"
                />
                <span>
                  <strong>{structureNodeName(item.name, t)}</strong>
                </span>
                <span className="document-structure-option-status">
                  {item.legacy
                    ? t('documentAssociations.legacyNode')
                    : localizedStatusLabel(item.node_status, t)}
                </span>
              </label>
            );
          })}
        </div>
      )}
      {options.some((item) => item.legacy) ? (
        <aside className="document-structure-legacy-help">
          <strong>{t('documentAssociations.legacyHelpTitle')}</strong>
          <p>{t('documentAssociations.legacyHelp')}</p>
          <a className="button secondary" href="/organization/structure">
            {t('documentAssociations.resolveLegacy')}
          </a>
        </aside>
      ) : null}
      <div className="document-structure-selection-summary" aria-live="polite">
        <strong>{t('documentAssociations.selectedCount', { count: selected.size })}</strong>
        {selected.size > 0 ? (
          <ul>
            {[...selected].map((nodeId) => {
              const item = byId.get(nodeId);
              return item ? (
                <li key={nodeId}>
                  <span>{structureNodeName(item.name, t)}</span>
                  <button
                    aria-label={t('documentAssociations.removeSelection', {
                      name: structureNodeName(item.name, t),
                    })}
                    disabled={disabled}
                    onClick={() => onToggle(nodeId, false)}
                    type="button"
                  >
                    ×
                  </button>
                </li>
              ) : null;
            })}
          </ul>
        ) : (
          <p>{t('documentAssociations.noneSelected')}</p>
        )}
      </div>
    </div>
  );
}

function AddDocuments({
  acceptedExtensions,
  acceptedMediaTypes,
  structureOptions,
  maxAssociations,
  canReadStructure,
  onCompleted,
}: {
  acceptedExtensions: string[];
  acceptedMediaTypes: string[];
  structureOptions: DocumentOrganizationStructureOption[];
  maxAssociations: number;
  canReadStructure: boolean;
  onCompleted: () => Promise<void>;
}) {
  const { t } = useI18n();
  const { organization } = useOrganization();
  const inputRef = useRef<HTMLInputElement>(null);
  const [types, setTypes] = useState<DocumentConfigurationOption[]>([]);
  const [documentTypeId, setDocumentTypeId] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState('');
  const [selectedNodeIds, setSelectedNodeIds] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const selectedType = types.find((item) => item.id === documentTypeId);
  const uploadConfig = record(selectedType?.config);
  const binaryConfig = record(uploadConfig.binary);
  const allowedMimeTypes = [
    uploadConfig.allowed_mime_types,
    uploadConfig.allowed_content_types,
    record(uploadConfig.upload).allowed_mime_types,
    record(uploadConfig.binary_upload).allowed_mime_types,
    record(binaryConfig.upload).allowed_mime_types,
  ].find((value) => Array.isArray(value)) as string[] | undefined;
  const acceptedFileValues = allowedMimeTypes?.length
    ? allowedMimeTypes
    : [...acceptedExtensions, ...acceptedMediaTypes];

  useEffect(() => {
    let cancelled = false;
    void listDocumentTypes()
      .then((items) => {
        if (cancelled) return;
        const available = items.filter((item) => item.status !== 'archived');
        setTypes(available);
        setDocumentTypeId(available[0]?.id ?? '');
      })
      .catch(() => {
        if (!cancelled) {
          setError(t('copy.document_configuration_could_not_be_loaded_ask_an_ad_3fc64838'));
        }
      });
    return () => { cancelled = true; };
  }, [organization?.id, t]);

  useEffect(() => {
    const availableIds = new Set(structureOptions.map((item) => item.id));
    setSelectedNodeIds((current) => new Set(
      [...current].filter((nodeId) => availableIds.has(nodeId)),
    ));
  }, [structureOptions]);

  function chooseFile(selected: File | null) {
    setFile(selected);
    setMessage(null);
    setError(null);
    if (selected && !title.trim()) setTitle(selected.name.replace(/\.[^.]+$/, ''));
  }

  function toggleNode(nodeId: string, checked: boolean) {
    setSelectedNodeIds((current) => {
      const next = new Set(current);
      if (checked) next.add(nodeId);
      else next.delete(nodeId);
      return next;
    });
    setMessage(null);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!organization || !file || !documentTypeId || submitting) return;
    setSubmitting(true);
    setError(null);
    setMessage(null);
    try {
      const descriptor = await fileDescriptor(file);
      const result = await orchestrateDocumentLifecycle({
        registration: {
          organization_id: organization.id,
          title: title.trim() || file.name,
          source_type: 'portal_upload',
          document_type_id: documentTypeId,
          external_reference: `portal-upload:${descriptor.checksum}`,
          description: `Uploaded from the portal as ${file.name}.`,
          source_ref: { file_name: file.name, interaction_surface: 'admin_portal' },
          metadata: { original_file_name: file.name },
          classification: {},
        },
        organization_node_ids: [...selectedNodeIds],
        file_name: file.name,
        content_type: file.type || 'application/octet-stream',
        content_bytes: descriptor.bytes,
        size_bytes: file.size,
        search_query: title.trim() || file.name,
        idempotency_key: `portal-document:${organization.id}:${descriptor.checksum}`,
        lifecycle_metadata: { interaction_surface: 'admin_portal' },
      });
      if (result.lifecycle_status === 'blocked') {
        throw new Error(`${t('feedback.documentAddFailed')} (${t('status.blocked')})`);
      }
      setMessage(t('feedback.documentAdded'));
      setFile(null);
      setTitle('');
      setSelectedNodeIds(new Set());
      if (inputRef.current) inputRef.current.value = '';
      await onCompleted();
    } catch (cause) {
      setError(localizedApiError(cause, t, 'feedback.documentAddFailed'));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="table-card add-documents" id="add-documents">
      <div className="section-header action-heading">
        <div>
          <span className="eyebrow"><LocalizedText id="copy.primary_action_29911442" /></span>
          <h2><LocalizedText id="shell.stepDocuments" /></h2>
          <p><LocalizedText id="copy.upload_a_supported_file_into_the_governed_document_l_e6c57cd5" /></p>
        </div>
      </div>
      <form className="document-upload-form" onSubmit={submit}>
        <label className="file-drop" htmlFor="document-file">
          <strong>{file ? file.name : <LocalizedText id="copy.choose_a_file_74b1d89d" />}</strong>
          <span>
            {file
              ? `${Math.max(1, Math.round(file.size / 1024))} KB`
              : <LocalizedText id="copy.available_formats_follow_the_active_document_configu_0238ba27" />}
          </span>
          <input
            accept={acceptedFileValues.join(',')}
            id="document-file"
            ref={inputRef}
            type="file"
            onChange={(event) => chooseFile(event.target.files?.[0] ?? null)}
          />
        </label>
        <div className="document-upload-fields">
          <label className="field-label" htmlFor="document-title">
            <LocalizedText id="copy.document_title_3859bdaa" />
          </label>
          <input
            className="field-control"
            id="document-title"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder={t('copy.a_clear_title_for_people_to_recognize_f1a732c5')}
          />
          <label className="field-label" htmlFor="document-type-select">
            <LocalizedText id="copy.document_type_300b6ef0" />
          </label>
          <select
            className="field-control"
            id="document-type-select"
            value={documentTypeId}
            onChange={(event) => setDocumentTypeId(event.target.value)}
          >
            {types.length === 0 ? (
              <option value=""><LocalizedText id="copy.no_document_types_configured_72ee6eb2" /></option>
            ) : null}
            {types.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
          <small className="muted-text">
            <LocalizedText id="copy.choose_the_configured_document_type_then_add_the_fil_ebf37570" />
          </small>
          <details className="inline-help">
            <summary><LocalizedText id="copy.supported_file_formats_48ca0910" /></summary>
            <p>
              {allowedMimeTypes?.length
                ? allowedMimeTypes.join(', ')
                : acceptedExtensions.length
                  ? acceptedExtensions.join(', ')
                  : <LocalizedText id="copy.formats_are_validated_by_the_configured_document_lif_662a7273" />}
            </p>
          </details>
        </div>
        <fieldset className="document-location-fieldset">
          <legend>{t('documentAssociations.locationTitle')}</legend>
          <p>{t('documentAssociations.uploadHelp')}</p>
          <p className="document-association-boundary">
            {t('documentAssociations.boundaryHelp')}
          </p>
          {canReadStructure ? (
            <OrganizationStructureSelector
              disabled={submitting}
              idPrefix="document-upload-structure"
              maxSelections={maxAssociations}
              onToggle={toggleNode}
              options={structureOptions}
              selected={selectedNodeIds}
            />
          ) : (
            <div className="document-structure-empty">
              <strong>{t('documentAssociations.structureAccessUnavailable')}</strong>
              <p>{t('documentAssociations.uploadWithoutAssociation')}</p>
            </div>
          )}
        </fieldset>
        <div className="document-upload-actions">
          <button
            className="button"
            disabled={!file || !documentTypeId || submitting}
            type="submit"
          >
            {submitting
              ? <LocalizedText id="copy.adding_document_8d2f0fac" />
              : <LocalizedText id="copy.add_document_3ead4932" />}
          </button>
        </div>
      </form>
      {message ? <p className="context-message success-message" role="status">{message}</p> : null}
      {error ? <p className="context-message context-error" role="alert">{error}</p> : null}
    </section>
  );
}

function AssociationSummary({ document }: { document: DocumentRegistryItem }) {
  const { t } = useI18n();
  const summary = document.organization_associations;
  if (!summary?.visible) {
    return <p className="document-association-summary">{t('documentAssociations.notVisible')}</p>;
  }
  if (summary.active_count === 0) {
    return <p className="document-association-summary">{t('documentAssociations.none')}</p>;
  }
  return (
    <div className="document-association-summary">
      <ul>
        {summary.active.map((item) => (
          <li key={`${item.code ?? item.name}:${item.name}`}>
            <strong>{structureNodeName(item.name, t)}</strong>
            {!item.available ? <span>{t('documentAssociations.unavailable')}</span> : null}
          </li>
        ))}
      </ul>
      {summary.has_more
        ? <small>{t('documentAssociations.moreCount', { count: summary.active_count - summary.active.length })}</small>
        : null}
    </div>
  );
}

function DocumentAssociationEditor({
  document,
  onCompleted,
}: {
  document: DocumentRegistryItem;
  onCompleted: () => Promise<void>;
}) {
  const { t } = useI18n();
  const [opened, setOpened] = useState(false);
  const [runtime, setRuntime] = useState<DocumentOrganizationAssociationRuntime | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [mutationKey, setMutationKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setConflict(false);
    try {
      const current = await getDocumentOrganizationAssociations(document.document_record_id);
      setRuntime(current);
      setSelected(new Set(current.active_associations.map((item) => item.organization_node_id)));
      setMutationKey(null);
    } catch (cause) {
      setError(localizedApiError(cause, t, 'documentAssociations.loadError'));
    } finally {
      setLoading(false);
    }
  }, [document.document_record_id, t]);

  async function open() {
    const nextOpened = !opened;
    setOpened(nextOpened);
    if (nextOpened && !runtime && !loading) await load();
  }

  function toggle(nodeId: string, checked: boolean) {
    setSelected((current) => {
      const next = new Set(current);
      if (checked) next.add(nodeId);
      else next.delete(nodeId);
      return next;
    });
    setMutationKey(null);
    setError(null);
    setConflict(false);
  }

  function cancel() {
    if (!runtime) return;
    setSelected(new Set(runtime.active_associations.map((item) => item.organization_node_id)));
    setMutationKey(null);
    setError(null);
    setConflict(false);
  }

  async function save() {
    if (!runtime || saving || !runtime.capabilities.administer) return;
    setSaving(true);
    setError(null);
    setConflict(false);
    const key = mutationKey ?? window.crypto.randomUUID();
    setMutationKey(key);
    const activeByNode = new Map(
      runtime.active_associations.map((item) => [item.organization_node_id, item]),
    );
    const archivedByNode = new Map(
      runtime.archived_associations.map((item) => [item.organization_node_id, item]),
    );
    const proposals: Array<{
      organization_node_id: string;
      intent: 'add' | 'retain' | 'archive' | 'restore';
    }> = [];
    for (const nodeId of selected) {
      proposals.push({
        organization_node_id: nodeId,
        intent: activeByNode.has(nodeId)
          ? 'retain'
          : archivedByNode.has(nodeId)
            ? 'restore'
            : 'add',
      });
    }
    for (const nodeId of activeByNode.keys()) {
      if (!selected.has(nodeId)) {
        proposals.push({ organization_node_id: nodeId, intent: 'archive' });
      }
    }
    try {
      const saved = await saveDocumentOrganizationAssociations(
        document.document_record_id,
        {
          expected_revision: runtime.revision,
          mutation_key: key,
          associations: proposals,
        },
      );
      setRuntime(saved);
      setSelected(new Set(saved.active_associations.map((item) => item.organization_node_id)));
      setMutationKey(null);
      await onCompleted();
    } catch (cause) {
      if (cause instanceof PlatformApiError && cause.status === 409) {
        setConflict(true);
        setError(t('documentAssociations.conflictHelp'));
      } else {
        setError(localizedApiError(cause, t, 'documentAssociations.saveError'));
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="document-association-editor">
      <div className="document-association-editor-heading">
        <div>
          <h4>{t('documentAssociations.locationTitle')}</h4>
          <AssociationSummary document={document} />
        </div>
        <button
          className="button secondary"
          disabled={loading}
          onClick={() => void open()}
          type="button"
        >
          {opened ? t('common.actions.close') : t('documentAssociations.manage')}
        </button>
      </div>
      {opened ? (
        <div className="document-association-editor-body">
          {loading && !runtime ? <p>{t('common.loading')}</p> : null}
          {runtime ? (
            <>
              <p className="document-association-boundary">
                {t('documentAssociations.boundaryHelp')}
              </p>
              <OrganizationStructureSelector
                disabled={saving || !runtime.capabilities.administer || conflict}
                idPrefix={`document-associations-${document.document_record_id}`}
                maxSelections={runtime.limits.max_associations_per_document}
                onToggle={toggle}
                options={runtime.structure_options}
                selected={selected}
              />
              {runtime.archived_associations.length > 0 ? (
                <div className="document-association-history">
                  <strong>{t('documentAssociations.historyTitle')}</strong>
                  <ul>
                    {runtime.archived_associations.map((item) => (
                      <li key={item.id}>
                        <span>{structureNodeName(item.node.name, t)}</span>
                        <span>
                          {item.node.available
                            ? t('documentAssociations.canRestore')
                            : t('documentAssociations.unavailable')}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {!runtime.capabilities.administer ? (
                <p>{t('documentAssociations.readOnly')}</p>
              ) : null}
              {error ? <p className="form-error" role="alert">{error}</p> : null}
              <div className="document-association-actions">
                {conflict ? (
                  <button
                    className="button secondary"
                    disabled={loading}
                    onClick={() => void load()}
                    type="button"
                  >
                    {t('documentAssociations.reloadCurrent')}
                  </button>
                ) : null}
                <button
                  className="button"
                  disabled={saving || conflict || !runtime.capabilities.administer}
                  onClick={() => void save()}
                  type="button"
                >
                  {saving ? t('documentAssociations.saving') : t('common.actions.save')}
                </button>
                <button
                  className="button secondary"
                  disabled={saving}
                  onClick={cancel}
                  type="button"
                >
                  {t('common.actions.cancel')}
                </button>
              </div>
            </>
          ) : null}
          {error && !runtime ? <p className="form-error" role="alert">{error}</p> : null}
        </div>
      ) : null}
    </section>
  );
}

function DocumentDetails({
  document,
  version,
  canReadStructure,
  onCompleted,
}: {
  document: DocumentRegistryItem;
  version?: DocumentWorkspaceVersion;
  canReadStructure: boolean;
  onCompleted: () => Promise<void>;
}) {
  const { t } = useI18n();
  const readiness = record(document.readiness);
  const diagnosticValues = [
    record(version?.processing).blocking_issues,
    record(version?.knowledge).blocking_issues,
  ].flatMap((value) => Array.isArray(value) ? value : []);
  return (
    <div className="document-detail">
      <section>
        <h4><LocalizedText id="copy.current_state_8e20a6a9" /></h4>
        <div className="status-sequence">
          <span><LocalizedText id="status.registered" /></span>
          <span className={booleanValue(readiness.processing_ready) ? 'is-ready' : ''}>
            <LocalizedText id="status.processed" />
          </span>
          <span className={booleanValue(readiness.knowledge_ready) ? 'is-ready' : ''}>
            <LocalizedText id="status.published" />
          </span>
          <span className={booleanValue(readiness.search_ready) ? 'is-ready' : ''}>
            <LocalizedText id="status.searchable" />
          </span>
        </div>
      </section>
      <section>
        <h4><LocalizedText id="copy.document_information_876cc5db" /></h4>
        <p>
          <LocalizedText id="copy.type_ee3fb11d" />
          {localizedProductLabel(
            document.document_type?.name,
            t,
            t('common.notSelected'),
          )}
          {' '}
          <LocalizedText id="copy.collection_12fdce09" />
          {localizedProductLabel(
            document.collection?.name,
            t,
            t('common.notSelected'),
          )}
        </p>
      </section>
      {canReadStructure ? (
        <DocumentAssociationEditor document={document} onCompleted={onCompleted} />
      ) : (
        <section>
          <h4>{t('documentAssociations.locationTitle')}</h4>
          <p>{t('documentAssociations.notVisible')}</p>
        </section>
      )}
      <section>
        <h4><LocalizedText id="copy.knowledge_and_indexing_4edbb3d7" /></h4>
        <p>
          <LocalizedText id="copy.published_knowledge_e4687c68" />
          {localizedStatusLabel(readiness.knowledge_ready, t)}
          {' '}
          <LocalizedText id="copy.search_index_b1fe0632" />
          {localizedStatusLabel(readiness.search_ready, t)}
        </p>
      </section>
      {diagnosticValues.length > 0 ? (
        <section>
          <h4><LocalizedText id="copy.action_needed_c9232862" /></h4>
          <ul className="compact-list">
            {diagnosticValues.map((issue, index) => (
              <li key={index}>{issueMessage(record(issue), t('dynamic.detailsAvailable'))}</li>
            ))}
          </ul>
        </section>
      ) : null}
      <details>
        <summary><LocalizedText id="common.advancedDetails" /></summary>
        <dl className="technical-details-grid">
          <dt><LocalizedText id="copy.document_record_1ea37c70" /></dt>
          <dd>{document.document_record_id}</dd>
          <dt><LocalizedText id="copy.document_version_68fe8f6f" /></dt>
          <dd>{version?.document_version_id ?? <LocalizedText id="common.notAvailable" />}</dd>
          <dt><LocalizedText id="copy.lifecycle_status_de4968ce" /></dt>
          <dd>{localizedStatusLabel(document.lifecycle_status, t)}</dd>
          <dt><LocalizedText id="copy.storage_status_4f02e9a6" /></dt>
          <dd>{localizedStatusLabel(version?.storage_status, t)}</dd>
        </dl>
      </details>
    </div>
  );
}

export function DocumentWorkspace({
  organizationNodeId = null,
}: {
  organizationNodeId?: string | null;
}) {
  const { t } = useI18n();
  const {
    capabilitiesError,
    capabilitiesErrorStatus,
    capabilitiesLoading,
    capabilitiesResolved,
    navigationCapabilities,
    refreshCapabilities,
  } = useOrganization();
  const [runtime, setRuntime] = useState<DocumentWorkspaceRuntime | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [stage, setStage] = useState('all');
  const [hashDocumentId, setHashDocumentId] = useState<string | null>(null);
  const [highlightedDocumentId, setHighlightedDocumentId] = useState<string | null>(null);
  const highlightTimeoutRef = useRef<number | null>(null);
  const requestedOrganizationNodeId = organizationNodeId?.trim() || null;
  const contextualNode = useMemo(
    () => requestedOrganizationNodeId
      ? runtime?.organization_associations.structure_options.find(
        (item) => item.id === requestedOrganizationNodeId,
      ) ?? null
      : null,
    [requestedOrganizationNodeId, runtime?.organization_associations.structure_options],
  );
  const invalidOrganizationNode = Boolean(
    requestedOrganizationNodeId && runtime && !contextualNode,
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRuntime(await getDocumentWorkspaceRuntime());
    } catch (cause) {
      setError(localizedApiError(cause, t, 'feedback.documentsLoadFailed'));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    if (capabilitiesLoading || !capabilitiesResolved) return;
    if (!navigationCapabilities?.documents.visible) {
      setLoading(false);
      return;
    }
    void load();
  }, [
    capabilitiesLoading,
    capabilitiesResolved,
    load,
    navigationCapabilities?.documents.visible,
  ]);

  useEffect(() => {
    const readHashDocumentId = () => {
      const encodedTarget = window.location.hash.slice(1);
      if (!encodedTarget.startsWith('document-')) {
        setHashDocumentId(null);
        setHighlightedDocumentId(null);
        return;
      }
      try {
        setHashDocumentId(decodeURIComponent(encodedTarget.slice('document-'.length)) || null);
      } catch {
        setHashDocumentId(null);
        setHighlightedDocumentId(null);
      }
    };
    readHashDocumentId();
    window.addEventListener('hashchange', readHashDocumentId);
    return () => window.removeEventListener('hashchange', readHashDocumentId);
  }, []);

  const nodeDocuments = useMemo(
    () => (runtime?.document_registry ?? []).filter((document) => (
      !requestedOrganizationNodeId
      || (
        contextualNode !== null
        && document.organization_associations?.active_node_ids?.includes(contextualNode.id) === true
      )
    )),
    [contextualNode, requestedOrganizationNodeId, runtime?.document_registry],
  );

  const documents = useMemo(
    () => nodeDocuments.filter((document) => {
      const matchesQuery = !query.trim()
        || document.title.toLowerCase().includes(query.trim().toLowerCase());
      return matchesQuery && (stage === 'all' || documentStage(document) === stage);
    }),
    [nodeDocuments, query, stage],
  );

  useEffect(() => {
    if (loading || !runtime || !hashDocumentId) return;
    const targetVisibleInContext = nodeDocuments.some(
      (document) => document.document_record_id === hashDocumentId,
    );
    if (!targetVisibleInContext) {
      setHighlightedDocumentId(null);
      return;
    }
    if (query || stage !== 'all') {
      setQuery('');
      setStage('all');
      return;
    }

    const frame = window.requestAnimationFrame(() => {
      const target = document.getElementById(`document-${hashDocumentId}`);
      if (!(target instanceof HTMLDetailsElement)) return;
      target.open = true;
      setHighlightedDocumentId(hashDocumentId);
      const summary = target.querySelector('summary');
      if (summary instanceof HTMLElement) summary.focus({ preventScroll: true });
      target.scrollIntoView({
        behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
        block: 'center',
      });
      if (highlightTimeoutRef.current !== null) {
        window.clearTimeout(highlightTimeoutRef.current);
      }
      highlightTimeoutRef.current = window.setTimeout(() => {
        setHighlightedDocumentId((current) => (
          current === hashDocumentId ? null : current
        ));
        highlightTimeoutRef.current = null;
      }, 4_000);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [hashDocumentId, loading, nodeDocuments, query, runtime, stage]);

  useEffect(() => () => {
    if (highlightTimeoutRef.current !== null) {
      window.clearTimeout(highlightTimeoutRef.current);
    }
  }, []);

  if (capabilitiesError && !capabilitiesResolved) {
    return (
      <section className="card workspace-state">
        <h2>
          <LocalizedText
            id={capabilitiesErrorStatus === 403
              ? 'copy.access_required_3d2f1a2e'
              : 'copy.document_access_could_not_be_evaluated_17520d4c'}
          />
        </h2>
        <p>{capabilitiesError}</p>
        {capabilitiesErrorStatus === 403 ? (
          <a className="button secondary" href="/security">
            <LocalizedText id="copy.open_users_access_471c8985" />
          </a>
        ) : (
          <button
            className="button secondary"
            type="button"
            onClick={() => void refreshCapabilities()}
          >
            <LocalizedText id="common.actions.retry" />
          </button>
        )}
      </section>
    );
  }
  if (
    capabilitiesResolved
    && !capabilitiesLoading
    && !navigationCapabilities?.documents.visible
  ) {
    return (
      <section className="card workspace-state">
        <span className="eyebrow"><LocalizedText id="copy.access_required_3d2f1a2e" /></span>
        <h2><LocalizedText id="copy.documents_are_unavailable_for_your_account_7d702c5b" /></h2>
        <p><LocalizedText id="copy.an_organization_administrator_must_grant_document_re_84e4e92a" /></p>
        <a className="button secondary" href="/security">
          <LocalizedText id="copy.open_users_access_471c8985" />
        </a>
      </section>
    );
  }
  if (loading && !runtime) {
    return (
      <section className="card workspace-state">
        <h2><LocalizedText id="copy.loading_documents_9f1e0ce4" /></h2>
        <p><LocalizedText id="copy.retrieving_persisted_document_lifecycle_state_13333707" /></p>
      </section>
    );
  }
  if (error && !runtime) {
    return (
      <section className="card workspace-state">
        <h2><LocalizedText id="copy.documents_unavailable_a06bb475" /></h2>
        <p>{error}</p>
        <button className="button secondary" type="button" onClick={() => void load()}>
          <LocalizedText id="common.actions.retry" />
        </button>
      </section>
    );
  }
  if (!runtime) return null;

  const summary = runtime.workspace_summary ?? {};
  const diagnostics = runtime.diagnostics ?? {};
  const diagnosticGroups = [
    diagnostics.blocking_issues ?? [],
    diagnostics.warnings ?? [],
    diagnostics.pending_capabilities ?? [],
  ];
  const associationRuntime = runtime.organization_associations;

  return (
    <div className="product-workspace" data-document-workspace="ready">
      {requestedOrganizationNodeId ? (
        <section
          aria-labelledby="document-organization-context-title"
          className="card inline-state"
          role={invalidOrganizationNode ? 'alert' : undefined}
        >
          <div>
            <span className="eyebrow">{t('documentAssociations.contextLabel')}</span>
            <h2 id="document-organization-context-title">
              {contextualNode
                ? t('documentAssociations.filteredTitle', {
                  name: structureNodeName(contextualNode.name, t),
                })
                : t('documentAssociations.invalidFilterTitle')}
            </h2>
            <p>
              {contextualNode
                ? t('documentAssociations.filteredHelp', {
                  type: localizedStructureNodeType(contextualNode.node_type, t),
                })
                : t('documentAssociations.invalidFilterHelp')}
            </p>
          </div>
          <a className="button secondary" href="/documents">
            {t('documentAssociations.clearFilter')}
          </a>
        </section>
      ) : null}
      {navigationCapabilities?.documents.action_available ? (
        <AddDocuments
          acceptedExtensions={runtime.upload_capabilities.accepted_extensions ?? []}
          acceptedMediaTypes={runtime.upload_capabilities.accepted_media_types ?? []}
          canReadStructure={associationRuntime.capabilities.read}
          maxAssociations={associationRuntime.limits.max_associations_per_document}
          onCompleted={load}
          structureOptions={associationRuntime.structure_options}
        />
      ) : (
        <section className="card inline-state" id="add-documents">
          <div>
            <h2><LocalizedText id="copy.add_documents_requires_additional_access_cb61d17d" /></h2>
            <p><LocalizedText id="copy.you_can_review_documents_but_document_administration_30bb942e" /></p>
          </div>
          <a className="button secondary" href="/security">
            <LocalizedText id="copy.review_access_0d73310f" />
          </a>
        </section>
      )}
      <section
        className="workspace-summary-strip"
        aria-label={t('copy.document_lifecycle_summary_7481d495')}
      >
        <div>
          <small><LocalizedText id="status.registered" /></small>
          <strong>{runtime.document_registry.length}</strong>
        </div>
        <div>
          <small><LocalizedText id="copy.processing_ready_41c146e6" /></small>
          <strong>{localizedStatusLabel(summary.processing_ready, t)}</strong>
        </div>
        <div>
          <small><LocalizedText id="copy.published_knowledge_8e386cc8" /></small>
          <strong>{localizedStatusLabel(summary.knowledge_ready, t)}</strong>
        </div>
        <div>
          <small><LocalizedText id="status.searchable" /></small>
          <strong>{localizedStatusLabel(summary.search_ready, t)}</strong>
        </div>
      </section>
      <section className="table-card">
        <div className="section-header table-heading">
          <div>
            <h2><LocalizedText id="pages.documents.title" /></h2>
            <p><LocalizedText id="copy.open_a_row_to_review_lifecycle_evidence_and_advanced_c4f562b6" /></p>
          </div>
          <button
            className="button secondary"
            disabled={loading}
            onClick={() => void load()}
            type="button"
          >
            {loading
              ? <LocalizedText id="common.actions.refreshing" />
              : <LocalizedText id="common.actions.refresh" />}
          </button>
        </div>
        <div className="basic-filters">
          <input
            aria-label={t('copy.filter_documents_f7ce976d')}
            className="field-control"
            placeholder={t('copy.filter_by_title_585efa75')}
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <select
            aria-label={t('copy.filter_by_lifecycle_state_fbc24bf4')}
            className="field-control"
            value={stage}
            onChange={(event) => setStage(event.target.value)}
          >
            <option value="all"><LocalizedText id="copy.all_states_1740d808" /></option>
            <option value="registered"><LocalizedText id="status.registered" /></option>
            <option value="processed"><LocalizedText id="status.processed" /></option>
            <option value="published"><LocalizedText id="status.published" /></option>
            <option value="indexed"><LocalizedText id="status.searchable" /></option>
            <option value="failed"><LocalizedText id="status.failed" /></option>
          </select>
        </div>
        {invalidOrganizationNode ? (
          <div className="empty-state">
            <strong>{t('documentAssociations.invalidFilterTitle')}</strong>
            <p>{t('documentAssociations.invalidFilterHelp')}</p>
            <a className="button secondary" href="/documents">
              {t('documentAssociations.clearFilter')}
            </a>
          </div>
        ) : contextualNode && nodeDocuments.length === 0 ? (
          <div className="empty-state">
            <strong>{t('documentAssociations.emptyNodeTitle', {
              name: structureNodeName(contextualNode.name, t),
            })}</strong>
            <p>{t('documentAssociations.emptyNodeHelp')}</p>
          </div>
        ) : runtime.document_registry.length === 0 ? (
          <div className="empty-state">
            <strong><LocalizedText id="copy.no_documents_yet_1837bb99" /></strong>
            <p><LocalizedText id="copy.add_your_first_document_to_make_governed_knowledge_a_c5c6be40" /></p>
            {navigationCapabilities?.documents.action_available ? (
              <a className="button" href="#add-documents">
                <LocalizedText id="copy.add_your_first_document_cc059937" />
              </a>
            ) : null}
          </div>
        ) : documents.length === 0 ? (
          <div className="empty-state">
            <strong><LocalizedText id="copy.no_documents_match_these_filters_af50037e" /></strong>
            <p><LocalizedText id="copy.clear_or_change_the_filters_to_see_other_documents_ea8eba5b" /></p>
          </div>
        ) : (
          <div className="document-list">
            {documents.map((document) => {
              const version = runtime.versions.find(
                (item) => item.document_record_id === document.document_record_id,
              );
              return (
                <details
                  aria-current={highlightedDocumentId === document.document_record_id
                    ? 'location'
                    : undefined}
                  className={`document-row${highlightedDocumentId === document.document_record_id
                    ? ' is-source-target'
                    : ''}`}
                  id={`document-${document.document_record_id}`}
                  key={document.document_record_id}
                >
                  <summary>
                    <span>
                      <strong>{document.title}</strong>
                      <small>
                        {localizedProductLabel(
                          document.document_type?.name,
                          t,
                          t('copy.document_e214b8a2'),
                        )}
                      </small>
                      <AssociationSummary document={document} />
                    </span>
                    <StatusPill value={documentStage(document)} />
                    <span className="document-row-meta">
                      <LocalizedText id="common.updated" />
                      <LocalizedDate value={document.latest_activity ?? version?.created_at} />
                    </span>
                  </summary>
                  <DocumentDetails
                    canReadStructure={associationRuntime.capabilities.read}
                    document={document}
                    onCompleted={load}
                    version={version}
                  />
                </details>
              );
            })}
          </div>
        )}
      </section>
      <details className="advanced-panel">
        <summary><LocalizedText id="copy.advanced_lifecycle_diagnostics_ca398a41" /></summary>
        <div className="advanced-panel-content">
          <div className="alerts-grid">
            {[
              'copy.blocking_issues_c74144eb',
              'copy.warnings_1430f976',
              'copy.pending_capabilities_84fd1f5a',
            ].map((labelKey, index) => (
              <article className="context-card" key={labelKey}>
                <div className="context-card-header">
                  <strong>{t(labelKey)}</strong>
                  <span>{diagnosticGroups[index].length}</span>
                </div>
                {diagnosticGroups[index].length ? (
                  <ul className="compact-list">
                    {diagnosticGroups[index].map((item, itemIndex) => (
                      <li key={itemIndex}>
                        {issueMessage(item, t('dynamic.detailsAvailable'))}
                      </li>
                    ))}
                  </ul>
                ) : <p><LocalizedText id="common.noItems" /></p>}
              </article>
            ))}
          </div>
        </div>
      </details>
    </div>
  );
}
