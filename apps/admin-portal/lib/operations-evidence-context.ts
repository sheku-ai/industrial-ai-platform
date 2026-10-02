export const OPERATIONS_EVIDENCE_QUERY_KEYS = {
  organizationId: 'evidence_organization',
  controlId: 'evidence_control',
  domain: 'evidence_domain',
  status: 'evidence_status',
} as const;

export type OperationsEvidenceContext = {
  organizationId: string;
  controlId: string;
  domain: string;
  status: string;
};

type SearchParameters = {
  get: (name: string) => string | null;
};

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const STABLE_CODE_PATTERN = /^[a-z0-9][a-z0-9._:-]{0,127}$/i;

function validStableCode(value: string): boolean {
  return STABLE_CODE_PATTERN.test(value);
}

export function buildOperationsEvidenceHref(context: OperationsEvidenceContext): string {
  const parameters = new URLSearchParams({
    [OPERATIONS_EVIDENCE_QUERY_KEYS.organizationId]: context.organizationId,
    [OPERATIONS_EVIDENCE_QUERY_KEYS.controlId]: context.controlId,
    [OPERATIONS_EVIDENCE_QUERY_KEYS.domain]: context.domain,
    [OPERATIONS_EVIDENCE_QUERY_KEYS.status]: context.status,
  });
  return `/operations?${parameters.toString()}`;
}

export function hasOperationsEvidenceParameters(parameters: SearchParameters): boolean {
  return Object.values(OPERATIONS_EVIDENCE_QUERY_KEYS).some((key) => parameters.get(key) !== null);
}

export function parseOperationsEvidenceContext(
  parameters: SearchParameters,
): OperationsEvidenceContext | null {
  const context = {
    organizationId: parameters.get(OPERATIONS_EVIDENCE_QUERY_KEYS.organizationId)?.trim() ?? '',
    controlId: parameters.get(OPERATIONS_EVIDENCE_QUERY_KEYS.controlId)?.trim() ?? '',
    domain: parameters.get(OPERATIONS_EVIDENCE_QUERY_KEYS.domain)?.trim() ?? '',
    status: parameters.get(OPERATIONS_EVIDENCE_QUERY_KEYS.status)?.trim() ?? '',
  };

  if (
    !UUID_PATTERN.test(context.organizationId)
    || !validStableCode(context.controlId)
    || !validStableCode(context.domain)
    || !validStableCode(context.status)
  ) {
    return null;
  }
  return context;
}
