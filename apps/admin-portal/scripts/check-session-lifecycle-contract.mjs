import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const root = path.resolve(import.meta.dirname, '..', '..');
const read = (relative) => fs.readFileSync(path.join(root, relative), 'utf8');

const model = read('api/app/identity/models.py');
const service = read('api/app/identity/service.py');
const authRoutes = read('api/app/api/routes/auth.py');
const adminRoutes = read('api/app/api/routes/platform_security_sessions.py');
const clientIp = read('api/app/security/client_ip.py');
const config = read('api/app/core/config.py');
const portalApi = read('admin-portal/lib/session-management-api.ts');
const selfUi = read('admin-portal/components/auth/MySessions.tsx');
const policyUi = read('admin-portal/components/security/SessionPolicyManager.tsx');
const adminUi = read('admin-portal/components/security/AdminUserSessions.tsx');
const device = read('admin-portal/lib/session-device.ts');

const checks = {
  persisted_policy: ['class SessionPolicy', 'idle_timeout_seconds', 'max_concurrent_sessions', 'remember_me_enabled', 'retention_days'].every((value) => model.includes(value)),
  persisted_session_evidence: ['last_activity_at', 'idle_expires_at', 'absolute_expires_at', 'revocation_reason', 'remember_me', 'client_ip', 'user_agent'].every((value) => model.includes(value)),
  validity_and_touch: ['absolute_expires_at <= observed_at', 'idle_expires_at <= observed_at', 'activity_write_interval_seconds', 'min('].every((value) => service.includes(value)),
  concurrency_governed: service.includes('auth-session|') && service.includes('pg_advisory_xact_lock') && service.includes('.with_for_update()') && service.includes('concurrent_session_limit') && service.includes('max_concurrent_sessions'),
  self_contract: ['@router.get("/sessions"', '@router.delete("/sessions/{session_id}"', '@router.post("/sessions/revoke-others"'].every((value) => authRoutes.includes(value)),
  administrative_contract: ['@router.get("/session-policy"', '@router.put("/session-policy"', '@router.get("/users/{user_id}/sessions"', '@router.delete("/users/{user_id}/sessions/{session_id}"', '@router.post("/users/{user_id}/sessions/revoke-all"', 'platform.security', 'administer'].every((value) => adminRoutes.includes(value)),
  no_secret_exposure: !portalApi.includes('token_hash') && !selfUi.includes('token_hash'),
  trusted_proxy_resolution: ['request.client.host', 'auth_trusted_proxy_networks', 'ip_network(', 'ip_address(', 'reversed(chain)'].every((value) => clientIp.includes(value)) && config.includes('auth_forwarded_ip_headers'),
  server_side_pagination: ['status_filter', '.offset(offset)', '.limit(limit)', 'func.count(AuthSession.id)'].every((value) => service.includes(value)) && authRoutes.includes('limit: int = Query') && adminRoutes.includes('limit: int = Query'),
  current_and_active_ordering: service.includes('ordering.insert(0') && service.includes('active_order') && service.includes('.order_by(*ordering)'),
  shared_filter_contract: ['active', 'expired', 'revoked', 'all'].every((value) => selfUi.includes(`value="${value}"`) && adminUi.includes(`value="${value}"`)),
  bounded_device_presentation: device.includes('Edg') && device.indexOf('const edge') < device.indexOf('const chrome') && device.includes('iPhone') && device.includes('unknownLabel'),
  portal_integrated: selfUi.includes('data-session-management="self"') && policyUi.includes('data-session-management="policy"') && adminUi.includes('data-session-management="administrative"') && portalApi.includes('/api/platform/security/session-policy'),
};

const result = { ...checks, passed: Object.values(checks).every(Boolean) };
process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
if (!result.passed) process.exitCode = 1;
