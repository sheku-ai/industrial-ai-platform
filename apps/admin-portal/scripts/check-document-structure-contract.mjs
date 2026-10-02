import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import ts from 'typescript';

const root = process.cwd();
const read = (path) => readFileSync(resolve(root, path), 'utf8');

const api = read('lib/document-workspace-api.ts');
const workspace = read('components/documents/DocumentWorkspace.tsx');
const styles = read('app/globals.css');
const english = JSON.parse(read('i18n/en.json'));
const spanish = JSON.parse(read('i18n/es.json'));
const workspaceSyntax = ts.createSourceFile(
  'DocumentWorkspace.tsx',
  workspace,
  ts.ScriptTarget.Latest,
  true,
  ts.ScriptKind.TSX,
);

const isItemProperty = (expression, property) => (
  ts.isPropertyAccessExpression(expression)
  && ts.isIdentifier(expression.expression)
  && expression.expression.text === 'item'
  && expression.name.text === property
);

let itemIdRendered = false;
let itemCodeRendered = false;
let localizedItemNameRendered = false;
const inspectPresentation = (node) => {
  if (
    ts.isJsxExpression(node)
    && node.expression
    && (ts.isJsxElement(node.parent) || ts.isJsxFragment(node.parent))
  ) {
    itemIdRendered ||= isItemProperty(node.expression, 'id');
    itemCodeRendered ||= isItemProperty(node.expression, 'code');
  }
  if (
    ts.isCallExpression(node)
    && ts.isIdentifier(node.expression)
    && node.expression.text === 'structureNodeName'
    && node.arguments.length > 0
    && isItemProperty(node.arguments[0], 'name')
  ) {
    localizedItemNameRendered = true;
  }
  ts.forEachChild(node, inspectPresentation);
};
inspectPresentation(workspaceSyntax);

const checks = {
  authoritative_endpoints:
    api.includes('/api/documents/${documentId}/organization-associations')
    && api.includes('saveDocumentOrganizationAssociations'),
  upload_is_single_request:
    workspace.includes('organization_node_ids: [...selectedNodeIds]')
    && !workspace.includes('saveDocumentOrganizationAssociations(result.document_record_id'),
  selector_uses_backend_runtime:
    workspace.includes('structureOptions={associationRuntime.structure_options}')
    && workspace.includes('options={runtime.structure_options}'),
  initially_empty:
    workspace.includes('useState<Set<string>>(new Set())')
    && !workspace.includes('setSelectedNodeIds(new Set([structureOptions[0]'),
  multiple_selection:
    workspace.includes('next.add(nodeId)')
    && workspace.includes('next.delete(nodeId)')
    && workspace.includes('type="checkbox"'),
  hierarchy_from_parent:
    workspace.includes('parent_node_id')
    && workspace.includes('orderedStructure(')
    && workspace.includes('byParent.get(item.id)'),
  archived_or_legacy_not_selectable:
    workspace.includes('!item.selectable')
    && workspace.includes("t('documentAssociations.legacyNode')"),
  legacy_resolution_is_structure_owned:
    workspace.includes("t('documentAssociations.legacyHelp')")
    && workspace.includes('href="/organization/structure"')
    && !workspace.includes('applyOrganizationStructureConvergence'),
  empty_structure_supported:
    workspace.includes('options.length === 0')
    && workspace.includes("t('documentAssociations.emptyStructureHelp')"),
  conflict_preserves_local_selection:
    workspace.includes('cause.status === 409')
    && workspace.includes('setConflict(true)')
    && workspace.includes('setSelected(new Set(current.active_associations')
    && workspace.includes("t('documentAssociations.reloadCurrent')"),
  double_submit_blocked:
    workspace.includes('if (!organization || !file || !documentTypeId || submitting) return')
    && workspace.includes('disabled={!file || !documentTypeId || submitting}'),
  error_preserves_upload_selection:
    workspace.indexOf('setSelectedNodeIds(new Set())')
      < workspace.indexOf('} catch (cause)'),
  no_uuid_as_primary_content:
    !itemIdRendered
    && !itemCodeRendered
    && localizedItemNameRendered,
  no_hardcoded_nodes_or_types:
    !workspace.includes("['structure_root'")
    && !workspace.includes("'HR'")
    && !workspace.includes("'HQ'"),
  lifecycle_states_are_separate:
    api.includes('association_status')
    && api.includes('node_status')
    && workspace.includes('document.lifecycle_status'),
  accessible_labels:
    workspace.includes('htmlFor={`${idPrefix}-search`}')
    && workspace.includes('htmlFor={`${idPrefix}-${item.id}`}')
    && workspace.includes('aria-label={t(\'documentAssociations.selectorLabel\')}'),
  responsive_without_global_overflow:
    styles.includes('.document-location-fieldset { min-width: 0;')
    && styles.includes('.document-structure-options')
    && styles.includes('@media (max-width: 620px)')
    && !styles.includes('.document-structure-selector { width: 100vw'),
  localized_contract:
    Boolean(english.documentAssociations?.boundaryHelp)
    && Boolean(spanish.documentAssociations?.boundaryHelp)
    && Boolean(english.documentAssociations?.resolveLegacy)
    && Boolean(spanish.documentAssociations?.resolveLegacy),
};

const result = { ...checks, passed: Object.values(checks).every(Boolean) };
console.log(JSON.stringify(result, null, 2));
process.exit(result.passed ? 0 : 1);
