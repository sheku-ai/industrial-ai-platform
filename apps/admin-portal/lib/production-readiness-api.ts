import { platformApi, type JsonObject } from './platform-api';

export type ProductionReadinessRuntime = {
  runtime_name: string;
  runtime_status: string;
  status: string;
  reason: string;
  product_acceptance: JsonObject;
  evidence_freshness: JsonObject;
  release_eligibility: JsonObject;
  workspace_summary: JsonObject;
  overall_production_readiness: JsonObject;
  gate_matrix: JsonObject[];
  blockers: JsonObject[];
  warnings: JsonObject[];
  evidence_contracts: ReadinessEvidenceContract[];
  recommendations: JsonObject[];
  next_actions: JsonObject[];
  evaluation_timestamp?: string | null;
  expires_at?: string | null;
  contract_version: string;
  runtime_version: string;
  production_score: JsonObject;
  postgresql_source_of_truth: boolean;
  side_effects_performed: boolean;
  external_calls_performed: boolean;
  llm_used: boolean;
  qdrant_used: boolean;
};

export type ReadinessGateEvidence = {
  gate_code: string;
  status: string;
  summary: string;
  evidence_ids: string[];
  components_evaluated: string[];
};

export type ReadinessEvidenceContract = {
  domain: string;
  status: string;
  reason: string;
  gate_results: ReadinessGateEvidence[];
  blockers: JsonObject[];
  warnings: JsonObject[];
  recommendations: JsonObject[];
  next_actions: JsonObject[];
  contract_version: string;
  runtime_version: string;
  evaluation_timestamp: string;
  expires_at?: string | null;
  evidence_origin: string;
  evaluation_duration: number;
  components_evaluated: string[];
  evidence_ids: string[];
  postgresql_source_of_truth: boolean;
};

export function getProductionReadinessRuntime(): Promise<ProductionReadinessRuntime> {
  return platformApi.get<ProductionReadinessRuntime>('/api/platform/production-readiness/runtime', productionHeaders, 60_000);
}

export type ProductionDomainSummary = {
  domain: string;
  status: string;
  mandatory_total: number;
  passed: number;
  failed: number;
  blocked: number;
  not_evaluated: number;
  blockers: JsonObject[];
  warnings: JsonObject[];
  components_evaluated: string[];
  evidence_origins: string[];
  evidence_references: string[];
  evaluated_at?: string | null;
  evidence_age_seconds?: number | null;
};

export type ProductionPreflightCheck = {
  setting_code: string;
  status: string;
  source: string;
  masked_value: string;
  reason: string;
  mandatory: boolean;
};

export type ProductionPreflight = {
  profile: string;
  status: string;
  checks: ProductionPreflightCheck[];
  blockers: JsonObject[];
  warnings: JsonObject[];
  postgresql_source_of_truth: boolean;
  secrets_exposed: boolean;
};

export type ProductionAcceptanceRun = {
  run_id: string;
  scope: string;
  organization_id?: string | null;
  status: string;
  functional_acceptance: ProductionDomainSummary;
  operational_acceptance: ProductionDomainSummary;
  security_acceptance: ProductionDomainSummary;
  recovery_acceptance: ProductionDomainSummary;
  deployment_acceptance: ProductionDomainSummary;
  capacity_acceptance: ProductionDomainSummary;
  portal_acceptance: ProductionDomainSummary;
  production_ready: boolean;
  mandatory_gate_counts: Record<string, number>;
  blockers: JsonObject[];
  warnings: JsonObject[];
  evidence_contracts: ReadinessEvidenceContract[];
  reason: string;
  recommendations: JsonObject[];
  next_actions: JsonObject[];
  evaluation_timestamp?: string | null;
  expires_at?: string | null;
  contract_version: string;
  runtime_version: string;
  requested_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  evaluated_at: string;
  result_hash?: string | null;
  reused: boolean;
  configuration_preflight?: ProductionPreflight | null;
};

export type ProductionWorkspaceRuntime = {
  runtime_name: string;
  runtime_status: string;
  current_status: string;
  local_product_acceptance: JsonObject;
  product_acceptance: JsonObject;
  evidence_freshness: JsonObject;
  release_eligibility: JsonObject;
  release_candidate_eligible: boolean;
  production_ready: boolean;
  latest_run?: ProductionAcceptanceRun | null;
  domain_summary: ProductionDomainSummary[];
  mandatory_gate_counts: Record<string, number>;
  blockers: JsonObject[];
  warnings: JsonObject[];
  configuration_preflight?: ProductionPreflight | null;
  operational_readiness: JsonObject;
  security_readiness: JsonObject;
  recovery_readiness: JsonObject;
  deployment_readiness: JsonObject;
  capacity_readiness: JsonObject;
  next_actions: JsonObject[];
  postgresql_source_of_truth: boolean;
  side_effects_performed: boolean;
  external_calls_performed: boolean;
  llm_used: boolean;
  qdrant_used: boolean;
};

export type RecoveryPolicy = {
  id: string;
  scope: string;
  organization_id?: string | null;
  name: string;
  status: string;
  database_backup_enabled: boolean;
  object_storage_backup_enabled: boolean;
  configuration_backup_enabled: boolean;
  rpo_minutes?: number | null;
  rto_minutes?: number | null;
  evidence_max_age_hours?: number | null;
  provider_type: string;
  provider_reference?: string | null;
};

export type RecoveryBackup = {
  id: string;
  scope: string;
  policy_id: string;
  status: string;
  backup_type: string;
  database_included: boolean;
  object_storage_included: boolean;
  configuration_included: boolean;
  artifact_count: number;
  manifest_hash?: string | null;
};

export type RecoveryRestore = {
  id: string;
  scope: string;
  policy_id: string;
  backup_execution_id: string;
  status: string;
  restore_target_type: string;
  destructive_operation: boolean;
  database_restored: boolean;
  object_storage_restored: boolean;
  configuration_restored: boolean;
};

export type RecoveryVerification = {
  id: string;
  restore_execution_id: string;
  verification_type: string;
  status: string;
  database_connectivity_verified: boolean;
  schema_version_verified: boolean;
  record_counts_verified: boolean;
  object_storage_access_verified: boolean;
  artifact_checksums_verified: boolean;
};

export type RecoveryReadiness = {
  evidence_contract: ReadinessEvidenceContract;
  status: string;
  reason: string;
  active_policy?: RecoveryPolicy | null;
  latest_backup?: RecoveryBackup | null;
  latest_restore?: RecoveryRestore | null;
  latest_restore_verification?: RecoveryVerification | null;
  gates: JsonObject[];
  blockers: JsonObject[];
  warnings: JsonObject[];
  recommendations: JsonObject[];
  next_actions: JsonObject[];
  evaluation_timestamp: string;
  expires_at?: string | null;
  contract_version: string;
  runtime_version: string;
  rpo: JsonObject;
  rto: JsonObject;
  evidence_freshness: JsonObject;
};

export type ProductionAcceptanceRequest = {
  scope: 'platform' | 'organization';
  organization_id?: string | null;
  idempotency_key: string;
  requested_by?: string | null;
};

export type CapacityVector = {
  concurrent_requests: number;
  ingestion: number;
  search: number;
  assistant: number;
  queue: number;
  worker: number;
  storage: number;
  database: number;
};

export type CapacityReadiness = {
  evidence_contract: ReadinessEvidenceContract;
  status: string;
  reason: string;
  scope: string;
  organization_id?: string | null;
  active_profile?: JsonObject | null;
  latest_evaluation?: JsonObject | null;
  latest_acceptance?: JsonObject | null;
  configured_capacity?: CapacityVector | null;
  observed_capacity?: CapacityVector | null;
  target_capacity?: CapacityVector | null;
  utilization?: CapacityVector | null;
  bottlenecks: JsonObject[];
  blockers: JsonObject[];
  warnings: JsonObject[];
  recommendations: JsonObject[];
  next_actions: JsonObject[];
  evaluation_timestamp: string;
  expires_at?: string | null;
  contract_version: string;
  runtime_version: string;
  blocker_count: number;
  recommendation_count: number;
  evidence_age_seconds?: number | null;
  evidence_age_hours?: number | null;
  gate_results: JsonObject[];
  postgresql_source_of_truth: boolean;
  llm_used: boolean;
  qdrant_used: boolean;
};

export type ObservabilityComponent = {
  id: string;
  name: string;
  component_type: string;
  status: string;
  version: string;
};

export type ObservabilityDependency = {
  id: string;
  name: string;
  dependency_type: string;
  status: string;
  observed_at: string;
};

export type ObservabilityHeartbeat = {
  id: string;
  component_id: string;
  status: string;
  observed_at: string;
  expires_at?: string | null;
};

export type ObservabilityReadiness = {
  evidence_contract: ReadinessEvidenceContract;
  status: string;
  reason: string;
  overall_health: string;
  availability_status: string;
  freshness_status: string;
  coverage_status: string;
  component_status: string;
  availability_percentage?: number | null;
  signal_coverage_percentage?: number | null;
  evidence_age_seconds?: number | null;
  components: ObservabilityComponent[];
  dependencies: ObservabilityDependency[];
  heartbeats: ObservabilityHeartbeat[];
  findings: JsonObject[];
  warnings: JsonObject[];
  blockers: JsonObject[];
  recommendations: JsonObject[];
  next_actions: JsonObject[];
  evaluation_timestamp: string;
  expires_at?: string | null;
  contract_version: string;
  runtime_version: string;
};

const productionHeaders = {
  'X-Authorization-Scope': 'platform',
};

export function getProductionWorkspaceRuntime(): Promise<ProductionWorkspaceRuntime> {
  return platformApi.get<ProductionWorkspaceRuntime>('/api/platform/production-acceptance/workspace', productionHeaders);
}

export function getCapacityReadiness(): Promise<CapacityReadiness> {
  return platformApi.get<CapacityReadiness>('/api/platform/capacity/readiness?scope=platform', productionHeaders);
}

export function getObservabilityReadiness(): Promise<ObservabilityReadiness> {
  return platformApi.get<ObservabilityReadiness>('/api/platform/observability/readiness', productionHeaders);
}

export function runProductionAcceptance(
  payload: ProductionAcceptanceRequest,
): Promise<ProductionAcceptanceRun> {
  return platformApi.post<ProductionAcceptanceRun>('/api/platform/production-acceptance/runs', payload, productionHeaders);
}

export function getRecoveryReadiness(): Promise<RecoveryReadiness> {
  return platformApi.get<RecoveryReadiness>('/api/platform/recovery/readiness?scope=platform', productionHeaders);
}

export function createRecoveryPolicy(payload: JsonObject): Promise<RecoveryPolicy> {
  return platformApi.post<RecoveryPolicy>('/api/platform/recovery/policies', payload, productionHeaders);
}

export function activateRecoveryPolicy(policyId: string): Promise<RecoveryPolicy> {
  return platformApi.post<RecoveryPolicy>(`/api/platform/recovery/policies/${policyId}/activate`, {}, productionHeaders);
}

export function registerRecoveryBackup(payload: JsonObject): Promise<RecoveryBackup> {
  return platformApi.post<RecoveryBackup>('/api/platform/recovery/backups', payload, productionHeaders);
}

export function addRecoveryBackupArtifact(backupId: string, payload: JsonObject): Promise<JsonObject> {
  return platformApi.post<JsonObject>(`/api/platform/recovery/backups/${backupId}/artifacts`, payload, productionHeaders);
}

export function completeRecoveryBackup(backupId: string, payload: JsonObject): Promise<RecoveryBackup> {
  return platformApi.post<RecoveryBackup>(`/api/platform/recovery/backups/${backupId}/complete`, payload, productionHeaders);
}

export function registerRecoveryRestore(payload: JsonObject): Promise<RecoveryRestore> {
  return platformApi.post<RecoveryRestore>('/api/platform/recovery/restores', payload, productionHeaders);
}

export function completeRecoveryRestore(restoreId: string, payload: JsonObject): Promise<RecoveryRestore> {
  return platformApi.post<RecoveryRestore>(`/api/platform/recovery/restores/${restoreId}/complete`, payload, productionHeaders);
}

export function createRecoveryVerification(restoreId: string, payload: JsonObject): Promise<RecoveryVerification> {
  return platformApi.post<RecoveryVerification>(`/api/platform/recovery/restores/${restoreId}/verifications`, payload, productionHeaders);
}

export function completeRecoveryVerification(verificationId: string, payload: JsonObject): Promise<RecoveryVerification> {
  return platformApi.post<RecoveryVerification>(`/api/platform/recovery/verifications/${verificationId}/complete`, payload, productionHeaders);
}

export type GovernedRelease = {
  id: string;
  release_code: string;
  version: string;
  edition: 'community' | 'enterprise';
  channel: string;
  status: string;
  source_repository: string;
  source_revision: string;
  source_branch?: string | null;
  prepared_at?: string | null;
  approved_at?: string | null;
};

export type GovernedBuild = {
  id: string;
  release_id: string;
  build_number: string;
  build_status: string;
  build_timestamp: string;
  target_platform: string;
  target_architecture: string;
  build_profile: string;
  reproducible: boolean;
};

export type GovernedArtifact = {
  id: string;
  artifact_code: string;
  artifact_type: string;
  component: string;
  edition: string;
  platform: string;
  architecture: string;
  artifact_reference: string;
  checksum_algorithm?: string | null;
  checksum?: string | null;
  digest_algorithm?: string | null;
  digest?: string | null;
  provenance_status: string;
  sbom_status: string;
  required: boolean;
  status: string;
};

export type ReleaseReadiness = {
  evidence_contract: ReadinessEvidenceContract;
  status: string;
  reason: string;
  release: GovernedRelease;
  build?: GovernedBuild | null;
  build_manifest?: JsonObject | null;
  deployment_manifest?: JsonObject | null;
  artifact_summary: JsonObject;
  artifacts: GovernedArtifact[];
  compatibility_summary: JsonObject;
  migration_summary: JsonObject;
  rollback_summary: JsonObject;
  acceptance?: JsonObject | null;
  acceptance_status: string;
  blockers: JsonObject[];
  warnings: JsonObject[];
  recommendations: JsonObject[];
  next_actions: JsonObject[];
  evaluation_timestamp: string;
  expires_at?: string | null;
  contract_version: string;
  runtime_version: string;
};

export type LatestReleaseReadiness = { found: boolean; readiness?: ReleaseReadiness | null };

export function getLatestReleaseReadiness(): Promise<LatestReleaseReadiness> {
  return platformApi.get<LatestReleaseReadiness>('/api/platform/releases/latest/readiness', productionHeaders);
}

export function listGovernedReleases(): Promise<GovernedRelease[]> {
  return platformApi.get<GovernedRelease[]>('/api/platform/releases', productionHeaders);
}

export function createGovernedRelease(payload: JsonObject): Promise<GovernedRelease> {
  return platformApi.post<GovernedRelease>('/api/platform/releases', payload, productionHeaders);
}

export function createGovernedBuild(releaseId: string, payload: JsonObject): Promise<GovernedBuild> {
  return platformApi.post<GovernedBuild>(`/api/platform/releases/${releaseId}/builds`, payload, productionHeaders);
}

export function registerGovernedBuildManifest(buildId: string, payload: JsonObject): Promise<JsonObject> {
  return platformApi.post<JsonObject>(`/api/platform/builds/${buildId}/manifest`, payload, productionHeaders);
}

export function completeGovernedBuild(buildId: string, payload: JsonObject): Promise<GovernedBuild> {
  return platformApi.post<GovernedBuild>(`/api/platform/builds/${buildId}/complete`, payload, productionHeaders);
}

export function registerGovernedDeploymentManifest(releaseId: string, payload: JsonObject): Promise<JsonObject> {
  return platformApi.post<JsonObject>(`/api/platform/releases/${releaseId}/deployment-manifest`, payload, productionHeaders);
}

export function registerGovernedArtifact(releaseId: string, payload: JsonObject): Promise<GovernedArtifact> {
  return platformApi.post<GovernedArtifact>(`/api/platform/releases/${releaseId}/artifacts`, payload, productionHeaders);
}

export function verifyGovernedArtifact(artifactId: string, payload: JsonObject): Promise<GovernedArtifact> {
  return platformApi.post<GovernedArtifact>(`/api/platform/artifacts/${artifactId}/verify`, payload, productionHeaders);
}

export function registerReleaseCompatibility(releaseId: string, payload: JsonObject): Promise<JsonObject> {
  return platformApi.post<JsonObject>(`/api/platform/releases/${releaseId}/compatibility`, payload, productionHeaders);
}

export function registerReleaseMigration(releaseId: string, payload: JsonObject): Promise<JsonObject> {
  return platformApi.post<JsonObject>(`/api/platform/releases/${releaseId}/migration-requirements`, payload, productionHeaders);
}

export function registerReleaseRollback(releaseId: string, payload: JsonObject): Promise<JsonObject> {
  return platformApi.post<JsonObject>(`/api/platform/releases/${releaseId}/rollback-target`, payload, productionHeaders);
}

export function evaluateGovernedRelease(releaseId: string): Promise<JsonObject> {
  return platformApi.post<JsonObject>(`/api/platform/releases/${releaseId}/evaluate`, {}, productionHeaders);
}
