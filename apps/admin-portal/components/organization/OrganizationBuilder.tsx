'use client';

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from 'react';
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { useI18n } from '../../i18n/I18nProvider';
import { ActionConfirmationDialog } from '../layout/ActionConfirmationDialog';
import {
  applyOrganizationStructureConvergence,
  getOrganizationStructureRuntime,
  previewOrganizationStructureConvergence,
  saveOrganizationStructure,
  type OrganizationNodeTypeCatalogItem,
  type OrganizationStructureConvergenceIssue,
  type OrganizationStructureConvergencePreview,
  type OrganizationStructureRuntime,
  type OrganizationStructureSaveInput,
} from '../../lib/organization-structure-api';
import { PlatformApiError, type JsonObject } from '../../lib/platform-api';
import { localizedApiError } from '../../lib/presentation';

type StructureNodeData = {
  label: string;
  persisted: boolean;
  node_type: string;
  type_name: string;
  code: string | null;
  name: string;
  description: string | null;
  metadata: JsonObject;
  status: 'active' | 'archived';
  original_status: 'active' | 'archived';
  legacy_type: boolean;
  preserve_legacy_position: boolean;
  [key: string]: unknown;
};

type StructureNode = Node<StructureNodeData>;
type StructureEdge = Edge<{ source: 'parent_node_id' | 'legacy_contains' | 'local' }>;
type Translate = (
  key: string,
  params?: Record<string, string | number>,
) => string;

type ConfirmationRequest = {
  confirmLabel: string;
  description: string;
  title: string;
  action: () => Promise<void>;
};

const NODE_TYPE_PRESENTATION_KEYS: Record<
  string,
  { name: string; description: string }
> = {
  structure_root: {
    name: 'structureWorkspace.nodeTypes.structureRoot.name',
    description: 'structureWorkspace.nodeTypes.structureRoot.description',
  },
  structure_group: {
    name: 'structureWorkspace.nodeTypes.structureGroup.name',
    description: 'structureWorkspace.nodeTypes.structureGroup.description',
  },
  structure_node: {
    name: 'structureWorkspace.nodeTypes.structureNode.name',
    description: 'structureWorkspace.nodeTypes.structureNode.description',
  },
};

function localizedCatalogName(
  item: OrganizationNodeTypeCatalogItem,
  t: Translate,
): string {
  const key = NODE_TYPE_PRESENTATION_KEYS[item.code]?.name;
  return key ? t(key) : item.name.trim() || t('structureWorkspace.unknownType');
}

function localizedCatalogDescription(
  item: OrganizationNodeTypeCatalogItem,
  t: Translate,
): string {
  const key = NODE_TYPE_PRESENTATION_KEYS[item.code]?.description;
  return key
    ? t(key)
    : item.description?.trim() || t('structureWorkspace.unknownTypeHelp');
}

function localizedNodeTypeName(
  code: string,
  backendName: string,
  t: Translate,
): string {
  const key = NODE_TYPE_PRESENTATION_KEYS[code]?.name;
  return key ? t(key) : backendName.trim() || t('structureWorkspace.unknownType');
}

function localizedNormalizationReason(reason: string, t: Translate): string {
  if (reason === 'legacy_contains_single_in_scope_parent_without_cycle') {
    return t('structureWorkspace.normalizationPreview.reason');
  }
  return t('structureWorkspace.normalizationPreview.reasonFallback');
}

const CONVERGENCE_ISSUE_KEYS: Record<string, string> = {
  organization_structure_convergence_target_required:
    'structureWorkspace.convergence.issues.targetRequired',
  organization_structure_convergence_target_unavailable:
    'structureWorkspace.convergence.issues.targetUnavailable',
  organization_structure_convergence_node_archived:
    'structureWorkspace.convergence.issues.nodeArchived',
  organization_structure_convergence_node_not_legacy:
    'structureWorkspace.convergence.issues.nodeNotLegacy',
  organization_structure_convergence_already_applied:
    'structureWorkspace.convergence.issues.alreadyApplied',
  organization_structure_convergence_contains_normalization_required:
    'structureWorkspace.convergence.issues.normalizationRequired',
  organization_structure_convergence_cycle:
    'structureWorkspace.convergence.issues.cycle',
  legacy_contains_endpoint_missing:
    'structureWorkspace.convergence.issues.endpointMissing',
  legacy_contains_cross_organization:
    'structureWorkspace.convergence.issues.crossOrganization',
  legacy_contains_self_reference:
    'structureWorkspace.convergence.issues.selfReference',
  legacy_contains_multiple_parents:
    'structureWorkspace.convergence.issues.multipleParents',
  legacy_contains_conflicts_with_primary_parent:
    'structureWorkspace.convergence.issues.parentConflict',
  legacy_contains_cycle:
    'structureWorkspace.convergence.issues.cycle',
  organization_structure_parent_not_found:
    'structureWorkspace.convergence.issues.parentMissing',
  organization_structure_parent_missing:
    'structureWorkspace.convergence.issues.parentMissing',
  organization_structure_parent_type_rejects_child:
    'structureWorkspace.convergence.issues.incompatibleParent',
  organization_structure_parent_cannot_have_children:
    'structureWorkspace.convergence.issues.incompatibleParent',
  organization_structure_parent_disallows_children:
    'structureWorkspace.convergence.issues.incompatibleParent',
  organization_structure_child_type_not_allowed:
    'structureWorkspace.convergence.issues.incompatibleParent',
  organization_structure_active_child_archived_parent:
    'structureWorkspace.convergence.issues.archivedParent',
};

function localizedConvergenceIssue(
  issue: OrganizationStructureConvergenceIssue | string,
  t: Translate,
): string {
  const code = typeof issue === 'string' ? issue : issue.code;
  return t(
    CONVERGENCE_ISSUE_KEYS[code]
      ?? 'structureWorkspace.convergence.issues.unknown',
  );
}

function StructureGraphNode({
  data,
}: NodeProps<StructureNode>) {
  const { t } = useI18n();
  const archived = data.status === 'archived';
  const displayName = data.name.trim() || t('structureWorkspace.unnamedNode');
  return (
    <div
      className={`structure-graph-node ${archived ? 'is-archived' : 'is-active'}`}
      role="group"
      aria-label={t('structureWorkspace.nodeAccessibleLabel', {
        name: displayName,
        status: t(archived ? 'status.archived' : 'status.active'),
      })}
    >
      <Handle
        type="target"
        position={Position.Top}
        isConnectable={!archived}
      />
      <div className="structure-graph-node-heading">
        <strong>{displayName}</strong>
        <span className="structure-graph-node-status">
          {t(archived ? 'status.archived' : 'status.active')}
        </span>
      </div>
      <span className="structure-graph-node-type">
        {localizedNodeTypeName(data.node_type, data.type_name, t)}
      </span>
      {data.legacy_type ? (
        <span className="structure-graph-node-legacy">
          {t('structureWorkspace.legacyType')}
        </span>
      ) : null}
      <Handle
        type="source"
        position={Position.Bottom}
        isConnectable={!archived}
      />
    </div>
  );
}

const STRUCTURE_NODE_TYPES = {
  organizationStructure: StructureGraphNode,
};

function catalogByCode(items: OrganizationNodeTypeCatalogItem[]) {
  return new Map(items.map((item) => [item.code, item]));
}

function graphFromRuntime(runtime: OrganizationStructureRuntime): {
  nodes: StructureNode[];
  edges: StructureEdge[];
} {
  const typeByCode = catalogByCode(runtime.node_type_catalog);
  return {
    nodes: runtime.nodes.map((item, index) => {
      const archived = item.status === 'archived';
      const catalogItem = typeByCode.get(item.node_type);
      return {
        id: item.id,
        type: 'organizationStructure',
        className: archived
          ? 'structure-node-archived'
          : 'structure-node-active',
        position: {
          x: Number(item.position.x ?? 100 + (index % 5) * 180),
          y: Number(item.position.y ?? 80 + Math.floor(index / 5) * 140),
        },
        data: {
          label: item.name,
          persisted: true,
          node_type: item.node_type,
          type_name: catalogItem?.name ?? '',
          code: item.code,
          name: item.name,
          description: item.description,
          metadata: item.metadata,
          status: item.status,
          original_status: item.status,
          legacy_type: catalogItem?.legacy === true,
          preserve_legacy_position: item.position_status === 'legacy_requires_review',
        },
        connectable: !archived,
        draggable: !archived,
      };
    }),
    edges: runtime.hierarchy.map((item) => ({
      id: item.source === 'legacy_contains'
        ? `legacy:${item.relationship_id ?? `${item.parent_node_id}:${item.child_node_id}`}`
        : `hierarchy:${item.child_node_id}`,
      source: item.parent_node_id,
      target: item.child_node_id,
      animated: item.source === 'legacy_contains',
      style: item.source === 'legacy_contains'
        ? { strokeDasharray: '6 5' }
        : undefined,
      data: { source: item.source },
    })),
  };
}

function descendants(rootId: string, edges: StructureEdge[]): Set<string> {
  const children = new Map<string, string[]>();
  for (const edge of edges) {
    const values = children.get(edge.source) ?? [];
    values.push(edge.target);
    children.set(edge.source, values);
  }
  const result = new Set<string>();
  const pending = [...(children.get(rootId) ?? [])];
  while (pending.length > 0) {
    const current = pending.pop();
    if (!current || result.has(current)) continue;
    result.add(current);
    pending.push(...(children.get(current) ?? []));
  }
  return result;
}

function createsCycle(source: string, target: string, edges: StructureEdge[]): boolean {
  if (source === target) return true;
  return descendants(target, edges).has(source);
}

function safeNodeLabel(node: StructureNode | undefined, fallback: string): string {
  const value = node?.data.name.trim();
  return value || fallback;
}

export function OrganizationBuilder() {
  const { t } = useI18n();
  const [runtime, setRuntime] = useState<OrganizationStructureRuntime | null>(null);
  const [nodes, setNodes, applyNodeChanges] = useNodesState<StructureNode>([]);
  const [edges, setEdges, applyEdgeChanges] = useEdgesState<StructureEdge>([]);
  const [selectedType, setSelectedType] = useState('');
  const [newNodeName, setNewNodeName] = useState('');
  const [selectedNodeId, setSelectedNodeId] = useState('');
  const [selectedNodeName, setSelectedNodeName] = useState('');
  const [selectedNodeDescription, setSelectedNodeDescription] = useState('');
  const [selectedNodeType, setSelectedNodeType] = useState('');
  const [normalizeLegacy, setNormalizeLegacy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [mutationKey, setMutationKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [convergenceTargets, setConvergenceTargets] = useState<
    Record<string, string>
  >({});
  const [convergencePreview, setConvergencePreview] =
    useState<OrganizationStructureConvergencePreview | null>(null);
  const [convergencePending, setConvergencePending] = useState(false);
  const [convergenceMutationKey, setConvergenceMutationKey] =
    useState<string | null>(null);
  const [convergenceError, setConvergenceError] = useState<string | null>(null);
  const [convergenceResult, setConvergenceResult] = useState<{
    revision: number;
    nodeChanges: number;
    hierarchyChanges: number;
    replayed: boolean;
  } | null>(null);
  const [confirmation, setConfirmation] = useState<ConfirmationRequest | null>(null);
  const [confirmationPending, setConfirmationPending] = useState(false);

  const catalog = useMemo(() => runtime?.node_type_catalog ?? [], [runtime?.node_type_catalog]);
  const typeByCode = useMemo(() => catalogByCode(catalog), [catalog]);
  const usableTypes = catalog.filter(
    (item) => item.available_for_new && item.status === 'active',
  );
  const selectedNode = nodes.find((item) => item.id === selectedNodeId);
  const selectedDocumentsHref = selectedNode?.data.persisted
    ? `/documents?organization_node_id=${encodeURIComponent(selectedNode.id)}`
    : null;
  const canAdminister = runtime?.capabilities.administer === true;
  const selectedCatalogType = typeByCode.get(selectedType);
  const selectedNodeCatalogType = selectedNode
    ? typeByCode.get(selectedNode.data.node_type)
    : undefined;
  const normalizationCandidates = runtime?.legacy_normalization_candidates ?? [];
  const legacyNormalizableCount = normalizationCandidates.length;
  const ambiguousLegacyCount = runtime?.legacy_relationships.filter(
    (item) => (
      item.status === 'active'
      && typeof item.normalization_blocker === 'string'
      && item.normalization_blocker.length > 0
    ),
  ).length ?? 0;
  const legacyNodes = nodes.filter(
    (item) => item.data.persisted && item.data.legacy_type,
  );
  const hasActiveLegacyRelationships = runtime?.legacy_relationships.some(
    (item) => item.status === 'active',
  ) ?? false;
  const convergenceAvailable = (
    legacyNodes.length > 0 || hasActiveLegacyRelationships
  );
  const displayedEdges = useMemo(
    () => edges.map((edge) => {
      if (edge.data?.source !== 'legacy_contains' || !normalizeLegacy) {
        return edge;
      }
      return {
        ...edge,
        animated: false,
        className: 'structure-edge-normalization-preview',
        label: t('structureWorkspace.normalizationPreview.edgeLabel'),
        labelStyle: { fill: '#0f172a', fontWeight: 800 },
        labelBgStyle: { fill: '#dcfce7', fillOpacity: 0.96 },
        labelBgPadding: [5, 3] as [number, number],
        labelBgBorderRadius: 5,
        style: {
          ...edge.style,
          stroke: '#15803d',
          strokeDasharray: '3 3',
          strokeWidth: 3,
        },
      };
    }),
    [edges, normalizeLegacy, t],
  );

  const replaceGraph = useCallback((
    payload: OrganizationStructureRuntime,
  ) => {
    const graph = graphFromRuntime(payload);
    setRuntime(payload);
    setNodes(graph.nodes);
    setEdges(graph.edges);
    setSelectedType('');
    setNewNodeName('');
    setSelectedNodeId('');
    setSelectedNodeName('');
    setSelectedNodeDescription('');
    setSelectedNodeType('');
    setNormalizeLegacy(false);
    setDirty(false);
    setConflict(false);
    setMutationKey(null);
    setConvergenceTargets({});
    setConvergencePreview(null);
    setConvergenceMutationKey(null);
    setConvergenceError(null);
    setConvergenceResult(null);
  }, [setEdges, setNodes]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      replaceGraph(await getOrganizationStructureRuntime());
    } catch (cause) {
      setError(localizedApiError(cause, t, 'structureWorkspace.errors.load'));
    } finally {
      setLoading(false);
    }
  }, [replaceGraph, t]);

  useEffect(() => {
    let cancelled = false;
    async function loadInitial() {
      setLoading(true);
      setError(null);
      try {
        const payload = await getOrganizationStructureRuntime();
        if (!cancelled) replaceGraph(payload);
      } catch (cause) {
        if (!cancelled) {
          setError(localizedApiError(
            cause,
            t,
            'structureWorkspace.errors.load',
          ));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void loadInitial();
    return () => {
      cancelled = true;
    };
  }, [replaceGraph, t]);

  function markChanged(message?: string) {
    setDirty(true);
    setConflict(false);
    setMutationKey(null);
    setError(null);
    if (message) setNotice(message);
  }

  function convergencePayloadTargets() {
    return legacyNodes.flatMap((node) => {
      const target = convergenceTargets[node.id];
      return target
        ? [{ node_id: node.id, target_node_type: target }]
        : [];
    });
  }

  function selectConvergenceTarget(nodeId: string, target: string) {
    setConvergenceTargets((current) => ({
      ...current,
      [nodeId]: target,
    }));
    setConvergencePreview(null);
    setConvergenceMutationKey(null);
    setConvergenceError(null);
    setConvergenceResult(null);
  }

  async function previewConvergence() {
    if (!runtime || pending || convergencePending || !canAdminister || dirty) return;
    setConvergencePending(true);
    setConvergenceError(null);
    setConvergenceResult(null);
    try {
      setConvergencePreview(await previewOrganizationStructureConvergence({
        targets: convergencePayloadTargets(),
        normalize_legacy_contains: true,
      }));
      setConvergenceMutationKey(null);
    } catch (cause) {
      setConvergencePreview(null);
      setConvergenceError(localizedApiError(
        cause,
        t,
        'structureWorkspace.convergence.errors.preview',
      ));
    } finally {
      setConvergencePending(false);
    }
  }

  async function applyConvergence() {
    if (
      !runtime
      || !convergencePreview?.ready
      || pending
      || convergencePending
      || !canAdminister
      || dirty
    ) return;
    const key = convergenceMutationKey ?? crypto.randomUUID();
    setConvergenceMutationKey(key);
    setConvergencePending(true);
    setPending(true);
    setConvergenceError(null);
    try {
      const result = await applyOrganizationStructureConvergence({
        targets: convergencePayloadTargets(),
        normalize_legacy_contains: true,
        expected_revision: convergencePreview.source_revision,
        mutation_key: key,
        preview_hash: convergencePreview.preview_hash,
      });
      const nodeChanges = result.changes.filter(
        (item) => item.resource === 'node',
      ).length;
      const hierarchyChanges = result.changes.filter(
        (item) => item.resource === 'relationship',
      ).length;
      replaceGraph(result.runtime);
      setConvergenceResult({
        revision: result.revision,
        nodeChanges,
        hierarchyChanges,
        replayed: result.replayed,
      });
    } catch (cause) {
      if (cause instanceof PlatformApiError && cause.status === 409) {
        setConvergenceError(
          t('structureWorkspace.convergence.errors.staleOrBlocked'),
        );
      } else {
        setConvergenceError(localizedApiError(
          cause,
          t,
          'structureWorkspace.convergence.errors.apply',
        ));
      }
    } finally {
      setConvergencePending(false);
      setPending(false);
    }
  }

  function selectNode(node: StructureNode | undefined) {
    setSelectedNodeId(node?.id ?? '');
    setSelectedNodeName(node?.data.name ?? '');
    setSelectedNodeDescription(node?.data.description ?? '');
    setSelectedNodeType(node?.data.node_type ?? '');
  }

  function addNode() {
    const catalogItem = typeByCode.get(selectedType);
    const name = newNodeName.trim();
    if (!catalogItem || !catalogItem.available_for_new || !name) {
      setError(t('structureWorkspace.errors.newNode'));
      return;
    }
    const id = `local:${crypto.randomUUID()}`;
    const node: StructureNode = {
      id,
      position: {
        x: 100 + (nodes.length % 5) * 40,
        y: 100 + (nodes.length % 7) * 40,
      },
      data: {
        label: name,
        persisted: false,
        node_type: catalogItem.code,
        type_name: catalogItem.name,
        code: null,
        name,
        description: null,
        metadata: {},
        status: 'active',
        original_status: 'active',
        legacy_type: false,
        preserve_legacy_position: false,
      },
    };
    setNodes((current) => [...current, node]);
    selectNode(node);
    setNewNodeName('');
    markChanged(t('structureWorkspace.notices.staged'));
  }

  function applySelectedNode() {
    if (!selectedNode || !selectedNodeName.trim()) return;
    const nextType = typeByCode.get(selectedNodeType);
    const typeChanged = selectedNodeType !== selectedNode.data.node_type;
    if (
      typeChanged
      && (!nextType || !nextType.available_for_new || nextType.status !== 'active')
    ) {
      setError(t('structureWorkspace.errors.typeUnavailable'));
      return;
    }
    setNodes((current) => current.map((node) => (
      node.id === selectedNode.id
        ? {
          ...node,
          data: {
            ...node.data,
            label: selectedNodeName.trim(),
            name: selectedNodeName.trim(),
            description: selectedNodeDescription.trim() || null,
            node_type: selectedNodeType,
            type_name: nextType?.name ?? node.data.type_name,
            legacy_type: nextType?.legacy === true,
          },
        }
        : node
    )));
    markChanged(t('structureWorkspace.notices.staged'));
  }

  function toggleArchiveSelected() {
    if (!selectedNode || !canAdminister) return;
    if (!selectedNode.data.persisted) {
      setNodes((current) => current.filter((node) => node.id !== selectedNode.id));
      setEdges((current) => current.filter(
        (edge) => edge.source !== selectedNode.id && edge.target !== selectedNode.id,
      ));
      selectNode(undefined);
      markChanged(t('structureWorkspace.notices.staged'));
      return;
    }
    const archiving = selectedNode.data.status === 'active';
    const impacted = descendants(selectedNode.id, edges);
    const affected = new Set([selectedNode.id, ...(archiving ? impacted : [])]);
    setNodes((current) => current.map((node) => {
      if (!affected.has(node.id)) return node;
      const status = archiving ? 'archived' : 'active';
      return {
        ...node,
        className: status === 'archived'
          ? 'structure-node-archived'
          : 'structure-node-active',
        connectable: status === 'active',
        draggable: status === 'active',
        data: {
          ...node.data,
          label: node.data.name,
          status,
        },
      };
    }));
    setSelectedNodeName(selectedNode.data.name);
    markChanged(t('structureWorkspace.notices.staged'));
  }

  async function runConfirmedAction() {
    if (!confirmation || confirmationPending || pending || convergencePending) return;
    setConfirmationPending(true);
    try {
      await confirmation.action();
      setConfirmation(null);
    } finally {
      setConfirmationPending(false);
    }
  }

  const onConnect = useCallback((connection: Connection) => {
    if (!connection.source || !connection.target || !canAdminister) return;
    const parent = nodes.find((item) => item.id === connection.source);
    const child = nodes.find((item) => item.id === connection.target);
    const parentType = parent ? typeByCode.get(parent.data.node_type) : undefined;
    const invalid = (
      !parent
      || !child
      || parent.data.status !== 'active'
      || child.data.status !== 'active'
      || parentType?.allows_children === false
      || (
        Boolean(parentType?.allowed_child_types.length)
        && !parentType?.allowed_child_types.includes(child.data.node_type)
      )
      || edges.some((edge) => edge.target === connection.target)
      || createsCycle(connection.source, connection.target, edges)
    );
    if (invalid) {
      setError(t('structureWorkspace.errors.invalidConnection'));
      return;
    }
    setEdges((current) => addEdge({
      ...connection,
      id: `local-edge:${crypto.randomUUID()}`,
      data: { source: 'local' },
    }, current));
    markChanged(t('structureWorkspace.notices.staged'));
  }, [canAdminister, edges, nodes, setEdges, t, typeByCode]);

  function onNodesChange(changes: NodeChange<StructureNode>[]) {
    const safeChanges = changes.filter((change) => change.type !== 'remove');
    applyNodeChanges(safeChanges);
    const positionedIds = new Set(
      safeChanges
        .filter((change) => change.type === 'position')
        .map((change) => change.id),
    );
    if (positionedIds.size > 0) {
      setNodes((current) => current.map((node) => (
        positionedIds.has(node.id)
          ? {
            ...node,
            data: { ...node.data, preserve_legacy_position: false },
          }
          : node
      )));
    }
    if (safeChanges.some((change) => change.type === 'position' && !change.dragging)) {
      markChanged();
    }
  }

  function onEdgesChange(changes: EdgeChange<StructureEdge>[]) {
    const allowed = changes.filter((change) => {
      if (change.type !== 'remove') return true;
      if (!canAdminister) return false;
      const edge = edges.find((item) => item.id === change.id);
      return edge?.data?.source !== 'legacy_contains';
    });
    applyEdgeChanges(allowed);
    if (allowed.some((change) => change.type === 'remove')) {
      markChanged(t('structureWorkspace.notices.staged'));
    }
  }

  async function save() {
    if (!runtime || pending || !canAdminister) return;
    const key = mutationKey ?? crypto.randomUUID();
    setMutationKey(key);
    setPending(true);
    setError(null);
    setNotice(null);
    const payload: OrganizationStructureSaveInput = {
      expected_revision: runtime.revision,
      mutation_key: key,
      nodes: nodes.map((node) => {
        let intent: OrganizationStructureSaveInput['nodes'][number]['intent'];
        if (!node.data.persisted) intent = 'create';
        else if (
          node.data.original_status === 'active'
          && node.data.status === 'archived'
        ) intent = 'archive';
        else if (
          node.data.original_status === 'archived'
          && node.data.status === 'active'
        ) intent = 'restore';
        else intent = 'update';
        return {
          ref: node.id,
          node_id: node.data.persisted ? node.id : null,
          intent,
          node_type: node.data.node_type,
          code: node.data.code,
          name: node.data.name,
          description: node.data.description,
          metadata: node.data.metadata,
          position: node.data.preserve_legacy_position
            ? {}
            : {
              x: Number(node.position.x),
              y: Number(node.position.y),
            },
        };
      }),
      hierarchy: edges
        .filter((edge) => (
          edge.data?.source !== 'legacy_contains' || normalizeLegacy
        ))
        .map((edge) => ({
          parent_ref: edge.source,
          child_ref: edge.target,
        })),
      additional_relationships: [],
      normalize_legacy_contains: normalizeLegacy,
    };
    try {
      const saved = await saveOrganizationStructure(payload);
      replaceGraph(saved);
      setNotice(t('structureWorkspace.notices.saved', { revision: saved.revision }));
    } catch (cause) {
      if (
        cause instanceof PlatformApiError
        && cause.status === 409
        && cause.message.includes('organization_structure_revision_conflict')
      ) {
        setConflict(true);
        setError(t('structureWorkspace.errors.conflict'));
      } else {
        setError(localizedApiError(
          cause,
          t,
          'structureWorkspace.errors.save',
        ));
      }
    } finally {
      setPending(false);
    }
  }

  if (loading) {
    return (
      <section className="card structure-state" role="status">
        <h2>{t('structureWorkspace.loading')}</h2>
      </section>
    );
  }

  if (!runtime) {
    return (
      <section className="card structure-state" role="alert">
        <h2>{t('structureWorkspace.errors.title')}</h2>
        <p>{error ?? t('structureWorkspace.errors.load')}</p>
        <button className="button secondary" type="button" onClick={() => void load()}>
          {t('common.actions.retry')}
        </button>
      </section>
    );
  }

  return (
    <div className="structure-workspace">
      <section className="workspace-summary-strip" aria-label={t('structureWorkspace.summary')}>
        <div>
          <small>{t('structureWorkspace.revision')}</small>
          <strong>{runtime.revision}</strong>
        </div>
        <div>
          <small>{t('structureWorkspace.activeNodes')}</small>
          <strong>{nodes.filter((node) => node.data.status === 'active').length}</strong>
        </div>
        <div>
          <small>{t('structureWorkspace.archivedNodes')}</small>
          <strong>{nodes.filter((node) => node.data.status === 'archived').length}</strong>
        </div>
        <div>
          <small>{t('structureWorkspace.rootPolicy')}</small>
          <strong>{t('structureWorkspace.multipleRoots')}</strong>
        </div>
      </section>

      {error ? <p className="form-error structure-message" role="alert">{error}</p> : null}
      {notice ? <p className="success-message structure-message" role="status">{notice}</p> : null}
      {conflict ? (
        <aside className="integration-notice structure-conflict">
          <strong>{t('structureWorkspace.conflictTitle')}</strong>
          <p>{t('structureWorkspace.conflictHelp')}</p>
          <button className="button danger" type="button" onClick={() => setConfirmation({ title: t('confirmation.discardStructureChangesTitle'), description: t('confirmation.discardStructureChangesEffect'), confirmLabel: t('structureWorkspace.reloadCurrent'), action: () => load() })}>
            {t('structureWorkspace.reloadCurrent')}
          </button>
        </aside>
      ) : null}

      {convergenceAvailable || convergenceResult ? (
        <section
          className="card structure-convergence"
          aria-labelledby="structure-convergence-title"
        >
          <div className="structure-convergence-heading">
            <div>
              <p className="eyebrow">
                {t('structureWorkspace.convergence.eyebrow')}
              </p>
              <h2 id="structure-convergence-title">
                {t('structureWorkspace.convergence.title')}
              </h2>
              <p>{t('structureWorkspace.convergence.help')}</p>
            </div>
            <span className="status-pill status-warning">
              {t('structureWorkspace.convergence.legacyCount', {
                count: legacyNodes.length,
              })}
            </span>
          </div>

          {dirty ? (
            <p className="structure-convergence-warning" role="status">
              {t('structureWorkspace.convergence.unsavedChanges')}
            </p>
          ) : null}
          {convergenceError ? (
            <p className="form-error" role="alert">{convergenceError}</p>
          ) : null}
          {convergenceResult ? (
            <div className="structure-convergence-result" role="status">
              <strong>
                {t(
                  convergenceResult.replayed
                    ? 'structureWorkspace.convergence.resultReplayed'
                    : 'structureWorkspace.convergence.resultApplied',
                  { revision: convergenceResult.revision },
                )}
              </strong>
              <p>{t('structureWorkspace.convergence.resultSummary', {
                nodes: convergenceResult.nodeChanges,
                relationships: convergenceResult.hierarchyChanges,
              })}</p>
              <a className="button secondary" href="/documents">
                {t('structureWorkspace.convergence.openDocuments')}
              </a>
            </div>
          ) : null}

          {legacyNodes.length > 0 ? (
            <div className="structure-convergence-targets">
              {legacyNodes.map((node) => (
                <article key={node.id}>
                  <div className="structure-convergence-node-heading">
                    <div>
                      <strong>{safeNodeLabel(
                        node,
                        t('structureWorkspace.unnamedNode'),
                      )}</strong>
                    </div>
                    <span>{t('structureWorkspace.convergence.currentType', {
                      type: localizedNodeTypeName(
                        node.data.node_type,
                        node.data.type_name,
                        t,
                      ),
                    })}</span>
                  </div>
                  <label
                    className="field-label"
                    htmlFor={`structure-convergence-target-${node.id}`}
                  >
                    {t('structureWorkspace.convergence.targetType')}
                  </label>
                  <select
                    className="field-control"
                    disabled={!canAdminister || convergencePending || dirty}
                    id={`structure-convergence-target-${node.id}`}
                    onChange={(event) => (
                      selectConvergenceTarget(node.id, event.target.value)
                    )}
                    value={convergenceTargets[node.id] ?? ''}
                  >
                    <option value="">{t('common.notSelected')}</option>
                    {usableTypes.map((item) => (
                      <option key={item.code} value={item.code}>
                        {localizedCatalogName(item, t)}
                      </option>
                    ))}
                  </select>
                  <p className="structure-field-help">
                    {t('structureWorkspace.convergence.targetHelp')}
                  </p>
                </article>
              ))}
            </div>
          ) : null}

          <div className="structure-convergence-actions">
            <button
              className="button secondary"
              type="button"
              aria-busy={convergencePending}
              disabled={
                !canAdminister
                || convergencePending
                || dirty
                || !convergenceAvailable
              }
              onClick={() => void previewConvergence()}
            >
              {t(
                convergencePending
                  ? 'structureWorkspace.convergence.previewing'
                  : 'structureWorkspace.convergence.previewAction',
              )}
            </button>
            <a className="button secondary" href="/documents">
              {t('structureWorkspace.convergence.openDocuments')}
            </a>
          </div>

          {convergencePreview ? (
            <div className="structure-convergence-preview">
              <div className="structure-convergence-preview-heading">
                <div>
                  <h3>{t('structureWorkspace.convergence.previewTitle')}</h3>
                  <p>{t('structureWorkspace.convergence.previewRevision', {
                    revision: convergencePreview.source_revision,
                  })}</p>
                </div>
                <span className={`status-pill ${
                  convergencePreview.ready ? 'status-success' : 'status-error'
                }`}>
                  {t(
                    convergencePreview.ready
                      ? 'structureWorkspace.convergence.ready'
                      : 'structureWorkspace.convergence.blocked',
                  )}
                </span>
              </div>

              <div className="structure-convergence-preview-nodes">
                {convergencePreview.nodes.map((item) => {
                  const currentType = typeByCode.get(item.current_type.code);
                  return (
                    <article key={item.node_id}>
                      <div className="structure-convergence-node-heading">
                        <div>
                          <strong>{item.name.trim()
                            || t('structureWorkspace.unnamedNode')}</strong>
                        </div>
                        <span>{t(
                          item.status === 'archived'
                            ? 'status.archived'
                            : 'status.active',
                        )}</span>
                      </div>
                      <dl>
                        <div>
                          <dt>{t('structureWorkspace.convergence.currentTypeLabel')}</dt>
                          <dd>{currentType
                            ? localizedCatalogName(currentType, t)
                            : t('structureWorkspace.unknownType')}</dd>
                        </div>
                        <div>
                          <dt>{t('structureWorkspace.convergence.targetTypeLabel')}</dt>
                          <dd>{item.target_type
                            ? item.target_type.name.trim()
                              || t('structureWorkspace.unknownType')
                            : t('common.notSelected')}</dd>
                        </div>
                        <div>
                          <dt>{t('structureWorkspace.convergence.currentParent')}</dt>
                          <dd>{item.current_parent
                            ? item.current_parent.name.trim()
                              || t('structureWorkspace.unnamedNode')
                            : t('structureWorkspace.convergence.rootNode')}</dd>
                        </div>
                        <div>
                          <dt>{t('structureWorkspace.convergence.projectedParent')}</dt>
                          <dd>{item.projected_parent
                            ? item.projected_parent.name.trim()
                              || t('structureWorkspace.unnamedNode')
                            : t('structureWorkspace.convergence.rootNode')}</dd>
                        </div>
                      </dl>
                      {item.blockers.map((issue, index) => (
                        <p
                          className="structure-convergence-blocker"
                          key={`${issue.code}:${index}`}
                        >
                          {localizedConvergenceIssue(issue, t)}
                        </p>
                      ))}
                      {item.warnings.map((issue, index) => (
                        <p
                          className="structure-convergence-warning"
                          key={`${issue.code}:${index}`}
                        >
                          {localizedConvergenceIssue(issue, t)}
                        </p>
                      ))}
                    </article>
                  );
                })}
              </div>

              {convergencePreview.hierarchy_changes.length > 0 ? (
                <section className="structure-convergence-hierarchy">
                  <h3>{t('structureWorkspace.convergence.hierarchyTitle')}</h3>
                  {convergencePreview.hierarchy_changes.map((item) => (
                    <article key={item.relationship_id}>
                      <strong>{item.child?.name.trim()
                        || t('structureWorkspace.unnamedNode')}</strong>
                      <span>{t('structureWorkspace.convergence.detectedParent', {
                        parent: item.detected_parent
                          ? item.detected_parent.name.trim()
                            || t('structureWorkspace.unnamedNode')
                          : t('structureWorkspace.convergence.unavailableParent'),
                      })}</span>
                      <span>{t('structureWorkspace.convergence.resultingParent', {
                        parent: item.projected_parent
                          ? item.projected_parent.name.trim()
                            || t('structureWorkspace.unnamedNode')
                          : t('structureWorkspace.convergence.rootNode'),
                      })}</span>
                      {item.blocker ? (
                        <p className="structure-convergence-blocker">
                          {localizedConvergenceIssue(item.blocker, t)}
                        </p>
                      ) : null}
                    </article>
                  ))}
                </section>
              ) : null}

              <div className="structure-convergence-impact">
                <h3>{t('structureWorkspace.convergence.impactTitle')}</h3>
                <ul>
                  <li>{t('structureWorkspace.convergence.impactIdentity')}</li>
                  <li>{t('structureWorkspace.convergence.impactMetadata')}</li>
                  <li>{t('structureWorkspace.convergence.impactReferences')}</li>
                  <li>{t('structureWorkspace.convergence.impactDocuments')}</li>
                </ul>
              </div>

              {convergencePreview.blockers.length > 0 ? (
                <div className="structure-convergence-issues" role="alert">
                  <strong>{t('structureWorkspace.convergence.blockersTitle')}</strong>
                  <ul>
                    {convergencePreview.blockers.map((issue, index) => (
                      <li key={`${issue.code}:${index}`}>
                        {localizedConvergenceIssue(issue, t)}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {convergencePreview.warnings.length > 0 ? (
                <div className="structure-convergence-warnings">
                  <strong>{t('structureWorkspace.convergence.warningsTitle')}</strong>
                  <ul>
                    {convergencePreview.warnings.map((issue, index) => (
                      <li key={`${issue.code}:${index}`}>
                        {localizedConvergenceIssue(issue, t)}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}

              <button
                className="button"
                type="button"
                aria-busy={convergencePending}
                disabled={
                  !convergencePreview.ready
                  || !convergencePreview.capabilities.apply
                  || convergencePending
                  || dirty
                }
                onClick={() => setConfirmation({ title: t('confirmation.applyConvergenceTitle'), description: t('confirmation.applyConvergenceEffect'), confirmLabel: t('structureWorkspace.convergence.applyAction'), action: applyConvergence })}
              >
                {t(
                  convergencePending
                    ? 'structureWorkspace.convergence.applying'
                    : 'structureWorkspace.convergence.applyAction',
                )}
              </button>
            </div>
          ) : null}
        </section>
      ) : null}

      <div className="builder-layout structure-builder-layout">
        <aside className="builder-panel structure-builder-panel">
          <div>
            <h2>{t('structureWorkspace.catalogTitle')}</h2>
            <p>{t(canAdminister
              ? 'structureWorkspace.catalogHelp'
              : 'structureWorkspace.readOnlyHelp')}</p>
          </div>

          <label className="field-label" htmlFor="structure-node-type">
            {t('structureWorkspace.nodeType')}
          </label>
          <select
            id="structure-node-type"
            className="field-control"
            value={selectedType}
            disabled={!canAdminister || pending}
            aria-describedby={selectedCatalogType ? 'structure-node-type-help' : undefined}
            onChange={(event) => setSelectedType(event.target.value)}
          >
            <option value="">{t('common.notSelected')}</option>
            {usableTypes.map((item) => (
              <option key={item.code} value={item.code}>
                {localizedCatalogName(item, t)}
              </option>
            ))}
          </select>
          {selectedCatalogType ? (
            <p className="structure-field-help" id="structure-node-type-help">
              {localizedCatalogDescription(selectedCatalogType, t)}
            </p>
          ) : null}
          <label className="field-label" htmlFor="structure-new-node-name">
            {t('structureWorkspace.nodeName')}
          </label>
          <input
            id="structure-new-node-name"
            className="field-control"
            value={newNodeName}
            maxLength={255}
            disabled={!canAdminister || pending}
            onChange={(event) => setNewNodeName(event.target.value)}
          />
          <button
            className="button secondary"
            type="button"
            disabled={!canAdminister || pending || !selectedType || !newNodeName.trim()}
            onClick={addNode}
          >
            {t('structureWorkspace.addNode')}
          </button>

          <hr className="structure-divider" />

          <label className="field-label" htmlFor="structure-selected-node">
            {t('structureWorkspace.selectedNode')}
          </label>
          <select
            id="structure-selected-node"
            className="field-control"
            value={selectedNodeId}
            disabled={pending}
            onChange={(event) => selectNode(
              nodes.find((node) => node.id === event.target.value),
            )}
          >
            <option value="">{t('common.notSelected')}</option>
            {nodes.map((node) => (
              <option key={node.id} value={node.id}>
                {safeNodeLabel(node, t('structureWorkspace.unnamedNode'))}
                {node.data.status === 'archived'
                  ? ` — ${t('status.archived')}`
                  : ''}
              </option>
            ))}
          </select>

          <label className="field-label" htmlFor="structure-edit-name">
            {t('structureWorkspace.nodeName')}
          </label>
          <input
            id="structure-edit-name"
            className="field-control"
            value={selectedNodeName}
            maxLength={255}
            disabled={
              !selectedNode
              || selectedNode.data.status === 'archived'
              || !canAdminister
              || pending
            }
            onChange={(event) => setSelectedNodeName(event.target.value)}
          />
          <label className="field-label" htmlFor="structure-edit-description">
            {t('structureWorkspace.description')}
          </label>
          <textarea
            id="structure-edit-description"
            className="field-control"
            value={selectedNodeDescription}
            maxLength={4000}
            disabled={
              !selectedNode
              || selectedNode.data.status === 'archived'
              || !canAdminister
              || pending
            }
            onChange={(event) => setSelectedNodeDescription(event.target.value)}
          />
          <label className="field-label" htmlFor="structure-edit-type">
            {t('structureWorkspace.nodeType')}
          </label>
          <select
            id="structure-edit-type"
            className="field-control"
            value={selectedNodeType}
            disabled={
              !selectedNode
              || selectedNode.data.status === 'archived'
              || selectedNode.data.legacy_type
              || !canAdminister
              || pending
            }
            aria-describedby={selectedNode ? 'structure-edit-type-help' : undefined}
            onChange={(event) => setSelectedNodeType(event.target.value)}
          >
            {catalog.map((item) => (
              <option
                key={item.code}
                value={item.code}
                disabled={!item.available_for_new && item.code !== selectedNode?.data.node_type}
              >
                {localizedCatalogName(item, t)}
                {item.legacy ? ` — ${t('structureWorkspace.legacyType')}` : ''}
              </option>
            ))}
          </select>
          {selectedNode && selectedNodeCatalogType ? (
            <p className="structure-field-help" id="structure-edit-type-help">
              {selectedNode.data.legacy_type
                ? t('structureWorkspace.legacyTypeCompatibility', {
                  type: selectedNodeCatalogType.name,
                })
                : localizedCatalogDescription(selectedNodeCatalogType, t)}
            </p>
          ) : null}
          <button
            className="button secondary"
            type="button"
            disabled={
              !selectedNode
              || !canAdminister
              || pending
              || selectedNode.data.status === 'archived'
              || !selectedNodeName.trim()
            }
            onClick={applySelectedNode}
          >
            {t('structureWorkspace.applyChanges')}
          </button>
          <button
            className={selectedNode?.data.status === 'archived'
              ? 'button secondary'
              : 'button danger administrative-destructive-action'}
            type="button"
            disabled={
              !selectedNode
              || !canAdminister
              || pending
            }
            onClick={() => {
              if (!selectedNode) return;
              if (selectedNode.data.status === 'archived') {
                toggleArchiveSelected();
                return;
              }
              const impacted = descendants(selectedNode.id, edges).size;
              setConfirmation({
                title: t(selectedNode.data.persisted ? 'confirmation.archiveOrganizationNodeTitle' : 'confirmation.removeStagedNodeTitle', { name: safeNodeLabel(selectedNode, t('structureWorkspace.unnamedNode')) }),
                description: t(selectedNode.data.persisted ? 'confirmation.archiveOrganizationNodeEffect' : 'confirmation.removeStagedNodeEffect', { count: impacted }),
                confirmLabel: t(selectedNode.data.persisted ? 'structureWorkspace.archiveNode' : 'structureWorkspace.removeStagedNode'),
                action: async () => { toggleArchiveSelected(); },
              });
            }}
          >
            {t(!selectedNode?.data.persisted
              ? 'structureWorkspace.removeStagedNode'
              : selectedNode.data.status === 'archived'
                ? 'structureWorkspace.restoreNode'
                : 'structureWorkspace.archiveNode')}
          </button>

          {legacyNormalizableCount > 0 ? (
            <label className="structure-normalize-option">
              <input
                type="checkbox"
                checked={normalizeLegacy}
                disabled={!canAdminister || pending}
                aria-describedby="structure-normalization-preview"
                onChange={(event) => {
                  setNormalizeLegacy(event.target.checked);
                  markChanged();
                }}
              />
              <span>
                <strong>{t('structureWorkspace.normalizeLegacy')}</strong>
                <small>{t('structureWorkspace.normalizeLegacyHelp', {
                  count: legacyNormalizableCount,
                })}</small>
              </span>
            </label>
          ) : null}

          {legacyNormalizableCount > 0 || ambiguousLegacyCount > 0 ? (
            <section
              className={`structure-normalization-preview ${
                normalizeLegacy ? 'is-selected' : 'is-persisted'
              }`}
              id="structure-normalization-preview"
              aria-labelledby="structure-normalization-preview-title"
            >
              <div className="structure-normalization-preview-heading">
                <strong id="structure-normalization-preview-title">
                  {t('structureWorkspace.normalizationPreview.title')}
                </strong>
                <span>
                  {t('structureWorkspace.normalizationPreview.selectedCount', {
                    selected: normalizeLegacy ? legacyNormalizableCount : 0,
                    total: legacyNormalizableCount,
                  })}
                </span>
              </div>
              {normalizationCandidates.map((candidate) => (
                <article key={candidate.candidate_id}>
                  <div>
                    <small>
                      {t('structureWorkspace.normalizationPreview.proposedParent')}
                    </small>
                    <strong>{candidate.proposed_parent.name.trim()
                      || t('structureWorkspace.unnamedNode')}</strong>
                  </div>
                  <span
                    className="structure-normalization-direction"
                    aria-hidden="true"
                  >
                    →
                  </span>
                  <div>
                    <small>
                      {t('structureWorkspace.normalizationPreview.proposedChild')}
                    </small>
                    <strong>{candidate.proposed_child.name.trim()
                      || t('structureWorkspace.unnamedNode')}</strong>
                  </div>
                  <p>
                    {t('structureWorkspace.normalizationPreview.relationship', {
                      relationship: candidate.legacy_relationship_type,
                    })}
                  </p>
                  <p>
                    {t('structureWorkspace.normalizationPreview.result')}
                  </p>
                  <p>
                    {localizedNormalizationReason(
                      candidate.normalizable_reason,
                      t,
                    )}
                  </p>
                </article>
              ))}
              <p className="structure-normalization-save-warning">
                {t('structureWorkspace.normalizationPreview.saveWarning')}
              </p>
              {ambiguousLegacyCount > 0 ? (
                <p className="structure-normalization-ambiguous">
                  {t('structureWorkspace.normalizationPreview.ambiguous', {
                    count: ambiguousLegacyCount,
                  })}
                </p>
              ) : null}
            </section>
          ) : null}

          <div className="structure-actions">
            <button
              className="button"
              type="button"
              disabled={!canAdminister || pending || !dirty}
              aria-busy={pending}
              onClick={() => void save()}
            >
              {t(pending ? 'structureWorkspace.saving' : 'common.actions.save')}
            </button>
            <button
              className="button secondary"
              type="button"
              disabled={pending || !dirty}
              onClick={() => replaceGraph(runtime)}
            >
              {t('common.actions.cancel')}
            </button>
            <button
              className="button secondary"
              type="button"
              disabled={pending}
              onClick={() => dirty
                ? setConfirmation({ title: t('confirmation.discardStructureChangesTitle'), description: t('confirmation.discardStructureChangesEffect'), confirmLabel: t('common.actions.refresh'), action: () => load() })
                : void load()}
            >
              {t('common.actions.refresh')}
            </button>
            {selectedDocumentsHref ? (
              <a className="button secondary" href={selectedDocumentsHref}>
                {t('structureWorkspace.convergence.openDocuments')}
              </a>
            ) : (
              <button className="button secondary" disabled type="button">
                {t('structureWorkspace.convergence.openDocuments')}
              </button>
            )}
          </div>
        </aside>

        <section
          className={`builder-canvas structure-builder-canvas ${
            pending ? 'is-pending' : ''
          }`}
          aria-label={t('structureWorkspace.canvas')}
          aria-busy={pending}
        >
          <ReactFlow
            nodes={nodes}
            edges={displayedEdges}
            nodeTypes={STRUCTURE_NODE_TYPES}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={(_event, node) => selectNode(node)}
            onConnect={onConnect}
            nodesConnectable={canAdminister && !pending}
            nodesDraggable={canAdminister && !pending}
            elementsSelectable={!pending}
            deleteKeyCode="Backspace"
            fitView
          >
            <MiniMap />
            <Controls />
            <Background />
          </ReactFlow>
        </section>
      </div>

      {runtime.legacy_warnings.length > 0 ? (
        <aside className="integration-notice structure-legacy-warning">
          <strong>{t('structureWorkspace.legacyWarningTitle')}</strong>
          <p>{t('structureWorkspace.legacyWarningHelp', {
            count: runtime.legacy_warnings.length,
          })}</p>
        </aside>
      ) : null}
      <ActionConfirmationDialog
        cancelLabel={t('common.actions.cancel')}
        confirmLabel={confirmation?.confirmLabel ?? t('common.actions.confirm')}
        description={confirmation?.description ?? ''}
        onCancel={() => { if (!confirmationPending && !pending && !convergencePending) setConfirmation(null); }}
        onConfirm={() => void runConfirmedAction()}
        open={Boolean(confirmation)}
        pending={confirmationPending || pending || convergencePending}
        title={confirmation?.title ?? ''}
      />
    </div>
  );
}
