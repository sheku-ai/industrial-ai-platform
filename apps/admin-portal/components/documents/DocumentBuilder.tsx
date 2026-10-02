'use client';

import { useI18n } from '../../i18n/I18nProvider';

import { LocalizedText } from '../layout/LocalizedText';
import { ActionConfirmationDialog } from '../layout/ActionConfirmationDialog';

import { useEffect, useMemo, useRef, useState } from 'react';

import { ensureOrganization, isUuid, platformApi, type PlatformEntity } from '../../lib/platform-api';
import { useAuth } from '../auth/AuthContext';

type FieldType = 'text' | 'number' | 'date' | 'select' | 'boolean';

type MetadataField = {
  id: string;
  name: string;
  label: string;
  type: FieldType;
  required: boolean;
};

type DocumentType = {
  id: string;
  name: string;
  code: string;
  classification: string;
  fields: MetadataField[];
};

type ApiDocumentType = PlatformEntity & {
  organization_id?: string | null;
  code: string;
  version: string;
  config?: { fields?: MetadataField[]; classification?: string };
};

type ConfirmationRequest = {
  confirmLabel: string;
  description: string;
  title: string;
  action: () => Promise<boolean>;
};

function toCode(value: string) {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
}

const DOCUMENT_TYPE_LABEL_KEYS: Record<string, string> = {
  'reference-document': 'documentConfiguration.types.referenceDocument',
};

const DOCUMENT_CLASSIFICATION_LABEL_KEYS: Record<string, string> = {
  internal: 'documentConfiguration.classifications.internal',
};

function documentCodeLabel(
  code: string | undefined,
  keys: Record<string, string>,
  unknownKey: string,
  translate: (key: string) => string,
): string {
  const normalized = String(code ?? '').trim().toLowerCase();
  return keys[normalized] ? translate(keys[normalized]) : translate(unknownKey);
}

export function DocumentBuilder() {
  const { t } = useI18n();
  const { principal } = useAuth();
  const membershipOrganizationIds = useMemo(
    () => new Set(
      principal?.memberships
        .filter((membership) => membership.status === 'active')
        .map((membership) => membership.organization_id) ?? [],
    ),
    [principal],
  );
  const [documentTypes, setDocumentTypes] = useState<DocumentType[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [newTypeName, setNewTypeName] = useState('');
  const [selectedName, setSelectedName] = useState('');
  const [selectedClassification, setSelectedClassification] = useState('internal');
  const [fieldName, setFieldName] = useState('');
  const [fieldType, setFieldType] = useState<FieldType>('text');
  const [fieldRequired, setFieldRequired] = useState(false);
  const [organization, setOrganization] = useState<PlatformEntity | null>(null);
  const [statusMessage, setStatusMessage] = useState(t('feedback.documentTypesLoading'));
  const [confirmation, setConfirmation] = useState<ConfirmationRequest | null>(null);
  const [pendingDestructiveAction, setPendingDestructiveAction] = useState(false);
  const destructiveActionInFlight = useRef(false);

  useEffect(() => {
    async function loadDocumentTypes() {
      try {
        const org = await ensureOrganization(membershipOrganizationIds);
        const apiTypes = await platformApi.get<ApiDocumentType[]>(
          '/api/documents/document-types?operational_only=true',
        );
        const organizationTypes = apiTypes.filter((item) => !item.organization_id || item.organization_id === org.id);
        setOrganization(org);

        if (organizationTypes.length > 0) {
          const mapped = organizationTypes.map((item) => ({
            id: item.id,
            name: item.name,
            code: item.code,
            classification: item.config?.classification ?? 'internal',
            fields: item.config?.fields ?? [],
          }));
          setDocumentTypes(mapped);
          setSelectedId(mapped[0].id);
          setSelectedName(mapped[0].name);
          setSelectedClassification(mapped[0].classification);
          setStatusMessage(t('copy.loaded_persisted_document_types_from_api_e5f9979c'));
        } else {
          setDocumentTypes([]);
          setSelectedId('');
          setSelectedName('');
          setSelectedClassification('internal');
          setStatusMessage(t('copy.no_document_types_are_configured_for_the_selected_or_d2e0ff23'));
        }
      } catch (error) {
        setStatusMessage(error instanceof Error ? error.message : t('feedback.documentTypesLoadFailed'));
      }
    }

    void loadDocumentTypes();
  }, [membershipOrganizationIds, t]);

  const selectedType = useMemo(() => documentTypes.find((item) => item.id === selectedId) ?? documentTypes[0], [documentTypes, selectedId]);

  useEffect(() => {
    if (!selectedType) {
      setSelectedName('');
      setSelectedClassification('internal');
      return;
    }
    setSelectedName(selectedType.name);
    setSelectedClassification(selectedType.classification);
  }, [selectedType]);

  const addDocumentType = () => {
    const trimmedName = newTypeName.trim();
    if (!trimmedName) return;
    const id = toCode(trimmedName);
    if (!id) return;
    setDocumentTypes((current) => [...current, { id, name: trimmedName, code: id, classification: 'internal', fields: [] }]);
    setSelectedId(id);
    setNewTypeName('');
    setStatusMessage(t('copy.document_type_added_locally_save_to_persist_it_0686a43e'));
  };

  const addField = () => {
    const trimmedName = fieldName.trim();
    if (!trimmedName || !selectedType) return;
    const id = `${toCode(trimmedName)}-${Date.now()}`;
    const field: MetadataField = { id, name: toCode(trimmedName), label: trimmedName, type: fieldType, required: fieldRequired };
    setDocumentTypes((current) => current.map((documentType) => documentType.id === selectedType.id ? { ...documentType, fields: [...documentType.fields, field] } : documentType));
    setFieldName('');
    setFieldRequired(false);
    setStatusMessage(t('copy.metadata_field_added_locally_save_to_persist_it_f50d5764'));
  };

  const updateSelectedType = () => {
    if (!selectedType || !selectedName.trim()) return;
    const nextCode = isUuid(selectedType.id) ? selectedType.code : toCode(selectedName);
    setDocumentTypes((current) => current.map((documentType) => (
      documentType.id === selectedType.id
        ? {
            ...documentType,
            name: selectedName.trim(),
            code: nextCode,
            classification: selectedClassification.trim() || 'internal',
          }
        : documentType
    )));
    setStatusMessage(t('copy.document_type_changes_staged_locally_save_to_persist_94cfdf75'));
  };

  const removeField = async (fieldId: string) => {
    if (!selectedType) return false;
    setDocumentTypes((current) => current.map((documentType) => (
      documentType.id === selectedType.id
        ? { ...documentType, fields: documentType.fields.filter((field) => field.id !== fieldId) }
        : documentType
    )));
    setStatusMessage(t('copy.metadata_field_removed_locally_save_to_persist_the_s_3b3ceb72'));
    return true;
  };

  const deleteSelectedType = async () => {
    if (!selectedType) return false;
    try {
      if (isUuid(selectedType.id)) {
        await platformApi.delete<void>(`/api/documents/document-types/${selectedType.id}`);
      }
      const remaining = documentTypes.filter((documentType) => documentType.id !== selectedType.id);
      setDocumentTypes(remaining);
      setSelectedId(remaining[0]?.id ?? '');
      setStatusMessage(t('copy.document_type_deleted_cabbc8ba'));
      return true;
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : t('feedback.documentTypeDeleteFailed'));
      return false;
    }
  };

  const runConfirmedAction = async () => {
    if (!confirmation || destructiveActionInFlight.current) return;
    destructiveActionInFlight.current = true;
    setPendingDestructiveAction(true);
    try {
      await confirmation.action();
      setConfirmation(null);
    } finally {
      destructiveActionInFlight.current = false;
      setPendingDestructiveAction(false);
    }
  };

  const saveToApi = async () => {
    try {
      const org = organization ?? (await ensureOrganization(membershipOrganizationIds));
      const saved: DocumentType[] = [];

      for (const documentType of documentTypes) {
        if (isUuid(documentType.id)) {
          const updated = await platformApi.patch<ApiDocumentType>(`/api/documents/document-types/${documentType.id}`, {
            name: documentType.name,
            description: 'Configured through Admin Portal.',
            config: { classification: documentType.classification, fields: documentType.fields },
          });
          saved.push({ ...documentType, id: updated.id });
          continue;
        }

        const created = await platformApi.post<ApiDocumentType>('/api/documents/document-types', {
          organization_id: org.id,
          code: documentType.code,
          name: documentType.name,
          description: 'Configured through Admin Portal.',
          version: '1.0',
          status: 'active',
          config: { classification: documentType.classification, fields: documentType.fields },
        });
        saved.push({ ...documentType, id: created.id });
      }

      setOrganization(org);
      setDocumentTypes(saved);
      setSelectedId(saved[0]?.id ?? selectedId);
      setStatusMessage(t('copy.document_types_persisted_through_platform_api_de5400fd'));
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : t('feedback.documentTypesPersistFailed'));
    }
  };

  return (
    <div className="builder-layout document-builder-layout">
      <aside className="builder-panel">
        <h2><LocalizedText id="copy.document_types_b3c8a1c8" /></h2>
        <p><LocalizedText id="copy.create_configurable_document_types_and_define_metada_131ba08d" /></p>
        <p aria-live="polite" className="muted-text builder-status">{statusMessage}</p>

        <label className="field-label" htmlFor="document-type"><LocalizedText id="copy.active_document_type_68f93d51" /></label>
        <select id="document-type" className="field-control" value={selectedId} onChange={(event) => setSelectedId(event.target.value)}>
          {documentTypes.map((documentType) => <option key={documentType.id} value={documentType.id}>{documentType.name}</option>)}
        </select>

        <label className="field-label" htmlFor="new-type"><LocalizedText id="copy.new_document_type_16aac793" /></label>
        <input id="new-type" className="field-control" value={newTypeName} onChange={(event) => setNewTypeName(event.target.value)} placeholder={t('copy.example_configurable_record_66072b6d')} />
        <button className="button secondary" type="button" onClick={addDocumentType}><LocalizedText id="copy.add_document_type_df1e43cc" /></button>

        <label className="field-label" htmlFor="field-name"><LocalizedText id="copy.metadata_field_d687e4e0" /></label>
        <input id="field-name" className="field-control" value={fieldName} onChange={(event) => setFieldName(event.target.value)} placeholder={t('copy.example_review_owner_8d7ec31b')} />
        <label className="field-label" htmlFor="field-type"><LocalizedText id="common.type" /></label>
        <select className="field-control" id="field-type" value={fieldType} onChange={(event) => setFieldType(event.target.value as FieldType)}>
          <option value="text"><LocalizedText id="copy.text_c3328c39" /></option>
          <option value="number"><LocalizedText id="copy.number_b7baa1d4" /></option>
          <option value="date"><LocalizedText id="copy.date_eb9a4bc1" /></option>
          <option value="select"><LocalizedText id="copy.select_85982229" /></option>
          <option value="boolean"><LocalizedText id="copy.boolean_b76ff490" /></option>
        </select>
        <button className="button secondary" type="button" onClick={addField}><LocalizedText id="copy.add_field_039c6315" /></button>
        <label className="field-label" htmlFor="type-name"><LocalizedText id="copy.selected_type_name_98814559" /></label>
        <input
          id="type-name"
          className="field-control"
          value={selectedName}
          disabled={!selectedType}
          onChange={(event) => setSelectedName(event.target.value)}
        />
        <label className="field-label" htmlFor="type-classification"><LocalizedText id="copy.classification_94c2a318" /></label>
        <input
          id="type-classification"
          className="field-control"
          value={selectedClassification}
          disabled={!selectedType}
          onChange={(event) => setSelectedClassification(event.target.value)}
        />
        <button className="button secondary" type="button" disabled={!selectedType || !selectedName.trim()} onClick={updateSelectedType}><LocalizedText id="copy.apply_type_changes_f2785e0b" /></button>

        <label className="field-label" htmlFor="field-required"><LocalizedText id="copy.required_field_04148d61" /></label>
        <select id="field-required" className="field-control" value={fieldRequired ? 'yes' : 'no'} onChange={(event) => setFieldRequired(event.target.value === 'yes')}>
          <option value="no"><LocalizedText id="copy.optional_0c6c4102" /></option>
          <option value="yes"><LocalizedText id="copy.required_eed6bfb4" /></option>
        </select>
        <div className="administrative-action-groups">
          <div className="administrative-actions-primary"><button className="button" type="button" onClick={saveToApi} disabled={documentTypes.length === 0 || pendingDestructiveAction}><LocalizedText id="copy.save_configuration_33e5a546" /></button></div>
          <div className="administrative-actions-destructive"><button className="button danger" type="button" onClick={() => selectedType && setConfirmation({ title: t('confirmation.deleteDocumentTypeTitle', { name: selectedType.name }), description: t('confirmation.deleteDocumentTypeEffect'), confirmLabel: t('copy.delete_selected_type_eb44d079'), action: deleteSelectedType })} disabled={!selectedType || pendingDestructiveAction}><LocalizedText id="copy.delete_selected_type_eb44d079" /></button></div>
        </div>
      </aside>

      <section className="builder-content">
        <div className="card">
          <h2>{selectedType?.name ?? <LocalizedText id="copy.no_document_type_selected_f77bf209" />}</h2>
          {selectedType ? <>
            <p><strong>{t('documentConfiguration.typeLabel')}:</strong> {documentCodeLabel(selectedType.code, DOCUMENT_TYPE_LABEL_KEYS, 'documentConfiguration.types.unknown', t)}</p>
            <small className="table-secondary">{t('governanceUx.technicalCode')}: <code>{selectedType.code}</code></small>
            <p><strong>{t('documentConfiguration.classificationLabel')}:</strong> {documentCodeLabel(selectedType.classification, DOCUMENT_CLASSIFICATION_LABEL_KEYS, 'documentConfiguration.classifications.unknown', t)}</p>
            <small className="table-secondary">{t('governanceUx.technicalCode')}: <code>{selectedType.classification}</code></small>
          </> : null}
          {!selectedType ? <p className="muted-text"><LocalizedText id="copy.create_a_document_type_to_define_metadata_classifica_ccce2d76" /></p> : null}
        </div>

        <div className="table-card">
          <h2><LocalizedText id="copy.metadata_schema_0cde6a74" /></h2>
          <table>
            <thead><tr><th><LocalizedText id="copy.label_74341e3c" /></th><th><LocalizedText id="common.name" /></th><th><LocalizedText id="common.type" /></th><th><LocalizedText id="copy.required_eed6bfb4" /></th><th /></tr></thead>
            <tbody>
              {selectedType?.fields.map((field) => (
                <tr key={field.id}>
                  <td>{field.label}</td>
                  <td>{field.name}</td>
                  <td>{field.type}</td>
                  <td>{field.required ? <LocalizedText id="common.yes" /> : <LocalizedText id="common.no" />}</td>
                  <td><button className="button danger" disabled={pendingDestructiveAction} type="button" onClick={() => setConfirmation({ title: t('confirmation.removeMetadataFieldTitle', { name: field.label }), description: t('confirmation.removeMetadataFieldEffect', { type: selectedType.name }), confirmLabel: t('common.actions.remove'), action: () => removeField(field.id) })}><LocalizedText id="common.actions.remove" /></button></td>
                </tr>
              ))}
              {(!selectedType || selectedType.fields.length === 0) ? (
                <tr><td colSpan={5}><LocalizedText id="copy.no_metadata_fields_are_configured_for_this_document__82305676" /></td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </section>
      <ActionConfirmationDialog cancelLabel={t('common.actions.cancel')} confirmLabel={confirmation?.confirmLabel ?? t('common.actions.confirm')} description={confirmation?.description ?? ''} onCancel={() => { if (!pendingDestructiveAction) setConfirmation(null); }} onConfirm={() => void runConfirmedAction()} open={Boolean(confirmation)} pending={pendingDestructiveAction} title={confirmation?.title ?? ''} />
    </div>
  );
}
