import { platformApi, type JsonObject } from './platform-api';

export type DocumentConfigurationOption = {
  id: string;
  code: string;
  name: string;
  status?: string;
  config?: JsonObject;
};

export type DocumentLifecycleResult = JsonObject & {
  lifecycle_status?: string;
  document_record_id?: string;
  document_version_id?: string;
  blocking_issues?: JsonObject[];
  warnings?: JsonObject[];
};

export type DocumentRegistryItem = {
  document_record_id: string;
  external_reference?: string | null;
  title: string;
  document_type: JsonObject;
  organization: JsonObject;
  collection: JsonObject;
  status: string;
  lifecycle_status: string;
  classification: JsonObject;
  current_version: JsonObject;
  latest_activity?: string | null;
  readiness: JsonObject;
  organization_associations?: {
    visible: boolean;
    active_count: number;
    active: DocumentOrganizationAssociationSummary[];
    active_node_ids?: string[];
    has_more?: boolean;
    has_unavailable: boolean;
  };
};

export type DocumentOrganizationStructureOption = {
  id: string;
  parent_node_id?: string | null;
  name: string;
  code: string;
  node_type: string;
  node_status: string;
  legacy: boolean;
  selectable: boolean;
};

export type DocumentOrganizationAssociationSummary = {
  name: string;
  code?: string | null;
  node_status: string;
  association_status: string;
  legacy: boolean;
  available: boolean;
};

export type DocumentOrganizationAssociation = {
  id: string;
  organization_node_id: string;
  association_status: 'active' | 'archived';
  node: {
    name: string;
    code?: string | null;
    node_type?: string | null;
    node_status: string;
    legacy: boolean;
    available: boolean;
  };
  created_at?: string | null;
  updated_at?: string | null;
  archived_at?: string | null;
  restored_at?: string | null;
};

export type DocumentOrganizationAssociationRuntime = {
  document_organization_association_schema_version: string;
  document: {
    id: string;
    title: string;
    status: string;
  };
  revision: number;
  active_associations: DocumentOrganizationAssociation[];
  archived_associations: DocumentOrganizationAssociation[];
  structure_options: DocumentOrganizationStructureOption[];
  capabilities: {
    read: boolean;
    administer: boolean;
  };
  limits: {
    max_associations_per_document: number;
  };
  warnings: JsonObject[];
  replayed: boolean;
  postgresql_source_of_truth: boolean;
  association_semantics: 'organizational_relation_only';
};

export type DocumentWorkspaceVersion = {
  document_version_id: string;
  document_record_id: string;
  version: number;
  created_at?: string | null;
  uploaded_at?: string | null;
  storage_status: string;
  processing_status: string;
  chunk_status: string;
  knowledge_publication_status: string;
  knowledge_index_status: string;
  enterprise_search_status: string;
  reference_tenant_status: string;
  lifecycle: Record<string, boolean>;
  storage: JsonObject;
  processing: JsonObject;
  chunks: JsonObject;
  knowledge: JsonObject;
  enterprise_search: JsonObject;
};

export type DocumentWorkspaceRuntime = {
  runtime_name: string;
  runtime_status: string;
  workspace_summary: JsonObject;
  document_registry: DocumentRegistryItem[];
  versions: DocumentWorkspaceVersion[];
  upload_capabilities: {
    accepted_extensions?: string[];
    accepted_media_types?: string[];
    contract_source?: string;
  };
  lifecycle: JsonObject;
  storage: JsonObject;
  processing: JsonObject;
  chunks: JsonObject;
  knowledge: JsonObject;
  enterprise_search: JsonObject;
  diagnostics: {
    blocking_issues?: JsonObject[];
    warnings?: JsonObject[];
    pending_capabilities?: JsonObject[];
    lifecycle_diagnostics?: JsonObject;
  };
  organization_associations: {
    capabilities: {
      read: boolean;
      administer: boolean;
    };
    structure_options: DocumentOrganizationStructureOption[];
    warnings: JsonObject[];
    limits: {
      max_associations_per_document: number;
    };
    association_semantics: 'organizational_relation_only';
  };
  postgresql_source_of_truth: boolean;
  llm_used: boolean;
  qdrant_used: boolean;
};

export function getDocumentWorkspaceRuntime(): Promise<DocumentWorkspaceRuntime> {
  return platformApi.get<DocumentWorkspaceRuntime>('/api/documents/workspace/runtime');
}

export function listDocumentTypes(): Promise<DocumentConfigurationOption[]> {
  return platformApi.get<DocumentConfigurationOption[]>('/api/documents/document-types?limit=200&operational_only=true');
}

export function orchestrateDocumentLifecycle(payload: JsonObject): Promise<DocumentLifecycleResult> {
  return platformApi.post<DocumentLifecycleResult>('/api/documents/lifecycle/orchestrate', payload, undefined, 120_000);
}

export function getDocumentOrganizationAssociations(
  documentId: string,
): Promise<DocumentOrganizationAssociationRuntime> {
  return platformApi.get<DocumentOrganizationAssociationRuntime>(
    `/api/documents/${documentId}/organization-associations`,
  );
}

export function saveDocumentOrganizationAssociations(
  documentId: string,
  payload: {
    expected_revision: number;
    mutation_key: string;
    associations: Array<{
      organization_node_id: string;
      intent: 'add' | 'retain' | 'archive' | 'restore';
    }>;
  },
): Promise<DocumentOrganizationAssociationRuntime> {
  return platformApi.put<DocumentOrganizationAssociationRuntime>(
    `/api/documents/${documentId}/organization-associations`,
    payload,
  );
}
