import { platformApi, type JsonObject } from './platform-api';

export type OrganizationNodeTypeCatalogItem = {
  id: string | null;
  code: string;
  name: string;
  description: string | null;
  status: string;
  allows_children: boolean;
  allowed_child_types: string[];
  presentation: JsonObject;
  display_order: number;
  available_for_new: boolean;
  edition: string;
  legacy: boolean;
};

export type OrganizationStructureNode = {
  id: string;
  parent_node_id: string | null;
  node_type: string;
  code: string;
  name: string;
  description: string | null;
  metadata: JsonObject;
  metadata_status?: 'valid' | 'legacy_requires_review';
  position: { x?: number; y?: number };
  position_status?: 'valid' | 'legacy_requires_review';
  status: 'active' | 'archived';
  created_at: string;
  updated_at: string;
};

export type OrganizationStructureHierarchy = {
  parent_node_id: string;
  child_node_id: string;
  source: 'parent_node_id' | 'legacy_contains';
  relationship_id?: string;
};

export type LegacyNormalizationCandidate = {
  candidate_id: string;
  relationship_id: string;
  legacy_relationship_type: string;
  proposed_parent: {
    node_id: string;
    code: string;
    name: string;
  };
  proposed_child: {
    node_id: string;
    code: string;
    name: string;
  };
  proposed_result: {
    authority: 'parent_node_id';
    parent_node_id: string;
    child_node_id: string;
    legacy_relationship_status_after_save: 'archived';
  };
  normalizable_reason: string;
};

export type OrganizationStructureRuntime = {
  organization_structure_schema_version: string;
  organization: {
    id: string;
    name: string;
    status: string;
  };
  revision: number;
  root_policy: 'multiple';
  capabilities: {
    read: boolean;
    administer: boolean;
    normalize_legacy: boolean;
  };
  node_type_catalog: OrganizationNodeTypeCatalogItem[];
  relationship_type_catalog: JsonObject[];
  nodes: OrganizationStructureNode[];
  hierarchy: OrganizationStructureHierarchy[];
  additional_relationships: JsonObject[];
  legacy_relationships: JsonObject[];
  legacy_normalization_candidates: LegacyNormalizationCandidate[];
  legacy_warnings: JsonObject[];
  limits: {
    max_nodes: number;
    max_additional_relationships: number;
  };
  replayed: boolean;
  postgresql_source_of_truth: boolean;
  external_calls_performed: boolean;
  generated_at: string;
};

export type OrganizationStructureNodeProposal = {
  ref: string;
  node_id: string | null;
  intent: 'create' | 'retain' | 'update' | 'archive' | 'restore';
  node_type: string;
  code: string | null;
  name: string;
  description: string | null;
  metadata: JsonObject;
  position: { x?: number; y?: number };
};

export type OrganizationStructureSaveInput = {
  expected_revision: number;
  mutation_key: string;
  nodes: OrganizationStructureNodeProposal[];
  hierarchy: Array<{
    parent_ref: string;
    child_ref: string;
  }>;
  additional_relationships: [];
  normalize_legacy_contains: boolean;
};

export type OrganizationStructureConvergenceTarget = {
  node_id: string;
  target_node_type: string;
};

export type OrganizationStructureNodeReference = {
  name: string;
  code: string;
};

export type OrganizationStructureConvergenceIssue = {
  code: string;
  node_id?: string;
  relationship_id?: string;
};

export type OrganizationStructureConvergenceNodePreview = {
  node_id: string;
  name: string;
  code: string;
  status: 'active' | 'archived';
  current_type: {
    code: string;
    legacy: boolean;
  };
  target_type: {
    code: string;
    name: string;
  } | null;
  current_parent: OrganizationStructureNodeReference | null;
  projected_parent: OrganizationStructureNodeReference | null;
  blockers: OrganizationStructureConvergenceIssue[];
  warnings: OrganizationStructureConvergenceIssue[];
  impact: {
    node_identity: 'preserved';
    metadata: 'preserved';
    references: 'preserved';
    document_associations: 'preserved';
  };
};

export type OrganizationStructureConvergenceHierarchyChange = {
  relationship_id: string;
  legacy_relationship_type: string;
  current_parent: OrganizationStructureNodeReference | null;
  detected_parent: OrganizationStructureNodeReference | null;
  child: OrganizationStructureNodeReference | null;
  projected_parent: OrganizationStructureNodeReference | null;
  normalizable: boolean;
  blocker: string | null;
};

export type OrganizationStructureConvergencePreview = {
  organization_structure_convergence_schema_version: string;
  source_revision: number;
  preview_hash: string;
  ready: boolean;
  nodes: OrganizationStructureConvergenceNodePreview[];
  hierarchy_changes: OrganizationStructureConvergenceHierarchyChange[];
  blockers: OrganizationStructureConvergenceIssue[];
  warnings: OrganizationStructureConvergenceIssue[];
  impact: JsonObject;
  capabilities: {
    preview: boolean;
    apply: boolean;
  };
  postgresql_source_of_truth: boolean;
  generated_at: string;
};

export type OrganizationStructureConvergenceApplyResult = {
  organization_structure_convergence_schema_version: string;
  applied: boolean;
  replayed: boolean;
  previous_revision: number;
  revision: number;
  changes: JsonObject[];
  runtime: OrganizationStructureRuntime;
  postgresql_source_of_truth: boolean;
};

export function getOrganizationStructureRuntime(): Promise<OrganizationStructureRuntime> {
  return platformApi.get<OrganizationStructureRuntime>(
    '/api/core/organization-structure/runtime',
  );
}

export function saveOrganizationStructure(
  payload: OrganizationStructureSaveInput,
): Promise<OrganizationStructureRuntime> {
  return platformApi.put<OrganizationStructureRuntime>(
    '/api/core/organization-structure/runtime',
    payload,
  );
}

export function previewOrganizationStructureConvergence(
  payload: {
    targets: OrganizationStructureConvergenceTarget[];
    normalize_legacy_contains: boolean;
  },
): Promise<OrganizationStructureConvergencePreview> {
  return platformApi.post<OrganizationStructureConvergencePreview>(
    '/api/core/organization-structure/convergence/preview',
    payload,
  );
}

export function applyOrganizationStructureConvergence(
  payload: {
    targets: OrganizationStructureConvergenceTarget[];
    normalize_legacy_contains: boolean;
    expected_revision: number;
    mutation_key: string;
    preview_hash: string;
  },
): Promise<OrganizationStructureConvergenceApplyResult> {
  return platformApi.post<OrganizationStructureConvergenceApplyResult>(
    '/api/core/organization-structure/convergence/apply',
    payload,
  );
}
