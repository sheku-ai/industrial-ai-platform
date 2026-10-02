import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const root = process.cwd();
const read = (path) => readFileSync(resolve(root, path), 'utf8');

const service = read('../api/app/services/security_management.py');
const routes = read('../api/app/api/routes/security_management.py');
const genericRoutes = read('../api/app/api/routes/security.py');
const crud = read('../api/app/api/routes/crud.py');
const migration = read('../api/alembic/versions/20260807_995_global_role_code_uniqueness.py');
const api = read('lib/global-role-management-api.ts');
const portal = read('components/security/GlobalRoleManager.tsx');
const platformRoles = read('../api/app/security/platform_roles.py');
const globalUsers = read('../api/app/services/global_user_management.py');

const creationStart = service.indexOf('        role = Role(', service.indexOf('class GlobalRoleManagementService'));
const creationEnd = service.indexOf('    def deactivate(', creationStart);
const creationBranch = service.slice(creationStart, creationEnd);
const creationOrder = [
  'role = Role(',
  'RolePermission(',
  'self._audit(',
  'self.db.commit()',
].map((token) => creationBranch.indexOf(token));

const checks = {
  governed_service: service.includes('class GlobalRoleManagementService'),
  advisory_transaction_lock: service.includes('pg_advisory_xact_lock'),
  rows_locked_before_reconcile: service.includes('statement.with_for_update()'),
  server_imposes_platform_invariants:
    service.includes('organization_id=None')
    && service.includes('"scope": "platform"')
    && service.includes('is_system=False')
    && service.includes('status="active"'),
  permissions_are_resolved_not_created:
    service.includes('select(Permission)')
    && service.includes('unknown_permission')
    && !service.slice(service.indexOf('class GlobalRoleManagementService')).includes('self.db.add(Permission('),
  exact_role_permissions: service.includes('"permission_keys": current_permission_keys == permission_keys'),
  no_intermediate_catalog_commit:
    creationOrder.every((position) => position >= 0)
    && creationOrder.every((position, index) => index === 0 || position > creationOrder[index - 1]),
  audit_is_authoritative:
    service.includes('AuditEvent(')
    && service.includes('AuditHistory(')
    && service.includes('actor_id=self.actor_reference')
    && service.includes('"correlation_id": self.correlation_id'),
  platform_admin_route_gate:
    routes.includes('context.scope_type != "platform"')
    && routes.includes('context.has_permission("platform.security", "administer")'),
  governed_routes_present:
    routes.includes('@router.post("/global-roles/reconcile"')
    && routes.includes('@router.post("/global-roles/{code}/deactivate"')
    && routes.includes('@router.post("/global-roles/{code}/activate"'),
  management_crud_blocks_global_roles:
    routes.includes('global_role_governed_endpoint_required')
    && routes.includes('_reject_global_role_mutation(role)'),
  generic_crud_blocks_global_roles:
    genericRoutes.includes('_guard_role_mutation')
    && genericRoutes.includes('_guard_role_permission_mutation')
    && genericRoutes.includes('_guard_permission_mutation')
    && crud.includes('mutation_guard'),
  migration_detects_duplicates:
    migration.includes('HAVING count(*) > 1')
    && migration.includes('Resolve the duplicated global role codes'),
  migration_enforces_partial_uniqueness:
    migration.includes('uq_security_roles_global_code')
    && migration.includes('unique=True')
    && migration.includes('organization_id IS NULL'),
  migration_has_downgrade: migration.includes('def downgrade()') && migration.includes('op.drop_index('),
  portal_uses_governed_api:
    api.includes('/api/security/management/global-roles/reconcile')
    && api.includes("'X-Authorization-Scope': 'platform'")
    && portal.includes('listGlobalRolePermissions()'),
  portal_has_no_role_or_permission_hardcode:
    !portal.includes('operations-read-only')
    && !portal.includes('platform.operations:read')
    && !api.includes('operations-read-only')
    && !api.includes('platform.operations:read'),
  shared_platform_role_semantics:
    service.includes('platform_role_criteria()')
    && globalUsers.includes('is_platform_role(item, require_active=True)')
    && platformRoles.includes('config.get("scope") == "platform"')
    && platformRoles.includes('Role.config["scope"].as_string() == "platform"'),
  catalog_does_not_filter_system_or_management_marker:
    service.includes('return [self._response(role) for role in roles]')
    && portal.includes('setRoles(roleCatalog)')
    && !portal.includes('roleCatalog.filter'),
  non_configurable_roles_remain_read_only:
    service.includes('global_role_not_configurable')
    && portal.includes('!role.configurable'),
};

const result = { ...checks, passed: Object.values(checks).every(Boolean) };
console.log(JSON.stringify(result, null, 2));
if (!result.passed) process.exitCode = 1;
