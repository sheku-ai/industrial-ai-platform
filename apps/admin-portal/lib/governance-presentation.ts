import type { GovernanceCenterRuntime } from './governance-center-api';
import type { JsonObject } from './platform-api';

export type NormalizedGovernanceDiagnostics = {
  operationalBlockers: JsonObject[];
  nonBlockingDegradations: JsonObject[];
  administrativeReviews: JsonObject[];
};

export function normalizeGovernanceDiagnostics(
  diagnostics: GovernanceCenterRuntime['diagnostics'] | null | undefined,
): NormalizedGovernanceDiagnostics {
  return {
    operationalBlockers: diagnostics?.blocking_issues ?? [],
    nonBlockingDegradations: [
      ...(diagnostics?.warnings ?? []),
      ...(diagnostics?.degraded_items ?? []),
    ],
    administrativeReviews: [
      ...(diagnostics?.pending_capabilities ?? []),
      ...(diagnostics?.governance_recommendations ?? []),
    ],
  };
}

const GOVERNANCE_SCOPE_KEYS: Record<string, string> = {
  selected_organization: 'governanceUx.scopes.selectedOrganization',
};

const GOVERNANCE_STATUS_KEYS: Record<string, string> = {
  blocked: 'status.blocked',
  degraded: 'status.degraded',
  failed: 'status.failed',
  needs_attention: 'status.degraded',
  not_evaluated: 'status.notEvaluated',
  pending: 'status.pending',
  ready: 'status.ready',
  unavailable: 'status.unavailable',
};

export function governanceScopeLabel(
  value: unknown,
  translate: (key: string) => string,
): string {
  const code = String(value ?? '').trim().toLowerCase();
  return GOVERNANCE_SCOPE_KEYS[code]
    ? translate(GOVERNANCE_SCOPE_KEYS[code])
    : translate('governanceUx.scopes.unknown');
}

export function governanceStatusLabel(
  value: unknown,
  translate: (key: string) => string,
): string {
  const code = String(value ?? '').trim().toLowerCase();
  return GOVERNANCE_STATUS_KEYS[code]
    ? translate(GOVERNANCE_STATUS_KEYS[code])
    : translate('status.unknown');
}
