import { resolveApiUrl } from './api-base-url';
import { ApiHttpError, httpRequest } from './http-client';

const REQUEST_TIMEOUT_MS = 15000;
const ORGANIZATION_STORAGE_KEY = 'industrial-ai-platform.organization-id';

export type JsonObject = Record<string, unknown>;

export class PlatformApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'PlatformApiError';
    this.status = status;
  }
}

export type PlatformEntity = {
  id: string;
  code?: string;
  slug?: string;
  name: string;
  description?: string | null;
  status?: string;
  config?: JsonObject;
  [key: string]: unknown;
};

export function organizationHeaders(organizationId: string): HeadersInit {
  return {
    'X-Authorization-Scope': 'organization',
    'X-Organization-ID': organizationId,
  };
}

function humanizeDetail(detail: unknown): string {
  if (typeof detail === 'string' && detail.trim()) {
    return detail.trim();
  }

  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (item && typeof item === 'object' && 'msg' in item) {
          return String((item as { msg: unknown }).msg);
        }
        return String(item);
      })
      .filter(Boolean)
      .join('; ');
  }

  if (detail && typeof detail === 'object') {
    const record = detail as Record<string, unknown>;
    return String(record.message ?? record.reason ?? record.code ?? 'The platform could not complete the request.');
  }

  return 'The platform could not complete the request.';
}

function friendlyError(status: number, body: string, statusText: string, platformScope: boolean): string {
  let detail: unknown = body || statusText;
  try {
    detail = body ? (JSON.parse(body) as { detail?: unknown }).detail ?? JSON.parse(body) : statusText;
  } catch {
    detail = body || statusText;
  }

  const message = humanizeDetail(detail);
  if (status === 401) {
    return 'Your authenticated session is no longer valid.';
  }
  if (status === 403) {
    if (platformScope) {
      return 'Your account does not have the required platform-level capability.';
    }
    return 'You do not have permission to perform this action in the active organization.';
  }
  if (status === 404) {
    return 'The requested item is no longer available in the active organization.';
  }
  if (status === 409) {
    return `This action is not valid for the item’s current state. ${message}`;
  }
  if (status === 422) {
    return `Review the submitted values. ${message}`;
  }
  if (status >= 500) {
    return 'The platform service could not complete this operation. Try again or review Platform Operations.';
  }
  return message;
}

async function request<T>(path: string, init?: RequestInit, timeoutMs = REQUEST_TIMEOUT_MS): Promise<T> {
  const target = resolveApiUrl(path);
  const selectedOrganizationId = window.localStorage.getItem(ORGANIZATION_STORAGE_KEY);
  const suppliedHeaders = new Headers(init?.headers);
  const platformScope = suppliedHeaders.get('X-Authorization-Scope')?.toLowerCase() === 'platform';
  const headers = new Headers(
    selectedOrganizationId && !platformScope ? organizationHeaders(selectedOrganizationId) : undefined,
  );
  suppliedHeaders.forEach((value, key) => headers.set(key, value));
  if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json');

  try {
    return await httpRequest<T>(target, {
      ...init,
      headers,
    }, { timeoutMs });
  } catch (cause) {
    if (cause instanceof ApiHttpError) {
      throw new PlatformApiError(
        cause.status,
        friendlyError(cause.status, cause.responseBody, cause.message, platformScope),
      );
    }
    throw cause;
  }
}

export const platformApi = {
  get: <T>(path: string, headers?: HeadersInit, timeoutMs?: number) => request<T>(path, { headers }, timeoutMs),
  post: <T>(path: string, body: unknown, headers?: HeadersInit, timeoutMs?: number) =>
    request<T>(path, { method: 'POST', body: JSON.stringify(body), headers }, timeoutMs),
  put: <T>(path: string, body: unknown, headers?: HeadersInit) =>
    request<T>(path, { method: 'PUT', body: JSON.stringify(body), headers }),
  patch: <T>(path: string, body: unknown, headers?: HeadersInit) =>
    request<T>(path, { method: 'PATCH', body: JSON.stringify(body), headers }),
  delete: <T>(path: string, headers?: HeadersInit) => request<T>(path, { method: 'DELETE', headers }),
};

export function listOrganizations(): Promise<PlatformEntity[]> {
  return platformApi.get<PlatformEntity[]>(
    '/api/core/organizations?limit=500&operational_only=true',
    { 'X-Authorization-Scope': 'platform' },
  );
}

export function isValidationOrganization(organization: PlatformEntity): boolean {
  const config = organization.config ?? {};
  return (
    config.smoke === true ||
    config.validation_generated === true ||
    config.scenario === 'local_product_acceptance' ||
    typeof config.execution_key === 'string'
  );
}

export function isSelectableOrganization(organization: PlatformEntity): boolean {
  return organization.status !== 'archived' && !isValidationOrganization(organization);
}

export function sortOrganizations(organizations: PlatformEntity[]): PlatformEntity[] {
  return [...organizations].sort((left, right) => {
    const leftReference = left.config?.reference_tenant === true || left.config?.canonical_product_reference === true;
    const rightReference = right.config?.reference_tenant === true || right.config?.canonical_product_reference === true;
    if (leftReference !== rightReference) return leftReference ? -1 : 1;
    return left.name.localeCompare(right.name);
  });
}

export async function ensureOrganization(allowedOrganizationIds: ReadonlySet<string>): Promise<PlatformEntity> {
  if (typeof window === 'undefined') {
    throw new Error('Organization context is only available in the browser.');
  }

  const selectedOrganizationId = window.localStorage.getItem(ORGANIZATION_STORAGE_KEY);
  if (!selectedOrganizationId) {
    throw new Error('Select an organization before using this workspace.');
  }

  const organizations = sortOrganizations(
    (await listOrganizations())
      .filter(isSelectableOrganization)
      .filter((organization) => allowedOrganizationIds.has(organization.id)),
  );
  const selected = organizations.find((organization) => organization.id === selectedOrganizationId);
  if (!selected) {
    window.localStorage.removeItem(ORGANIZATION_STORAGE_KEY);
    throw new Error('The selected organization is no longer available. Select another organization.');
  }

  return selected;
}

export function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
}
