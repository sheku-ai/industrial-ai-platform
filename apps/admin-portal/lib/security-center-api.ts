import { platformApi, type JsonObject } from './platform-api';

export type SecurityCenterRuntime = {
  runtime_name: string;
  runtime_status: string;
  workspace_summary: JsonObject;
  security_readiness: JsonObject;
  security_acceptance: JsonObject;
  security_findings: JsonObject[];
  security_evidence: JsonObject[];
  security_policies: JsonObject[];
  security_configuration: JsonObject;
  roles: JsonObject;
  permissions: JsonObject;
  policies: JsonObject;
  role_assignments: JsonObject;
  effective_permissions: JsonObject;
  scopes: JsonObject;
  policy_evaluation: JsonObject;
  access_diagnostics: JsonObject;
  security_audit: JsonObject;
  security_governance: JsonObject;
  reference_tenant_security: JsonObject;
  advanced_security_records?: JsonObject;
  pending_capabilities: JsonObject[];
  warnings: JsonObject[];
  recommendations: JsonObject[];
  postgresql_source_of_truth: boolean;
  side_effects_performed: boolean;
  external_calls_performed: boolean;
  llm_used: boolean;
  qdrant_used: boolean;
};

export function getSecurityCenterRuntime(): Promise<SecurityCenterRuntime> {
  return platformApi.get<SecurityCenterRuntime>('/api/security/center/runtime');
}
