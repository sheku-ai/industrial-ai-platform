'use client';

const REQUEST_TIMEOUT_MS = 15000;
const SESSION_EXPIRED_EVENT = 'industrial-ai-platform:session-expired';
const MUTATION_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

type CsrfToken = {
  csrf_token: string;
  header_name: string;
};

type RequestOptions = {
  csrf?: boolean;
  emitSessionExpired?: boolean;
  expectedStatuses?: readonly number[];
  timeoutMs?: number;
};

let csrfToken: CsrfToken | null = null;
let csrfRequest: Promise<CsrfToken> | null = null;
let csrfGeneration = 0;

export class ApiHttpError extends Error {
  readonly status: number;
  readonly detail: unknown;
  readonly responseBody: string;

  constructor(status: number, detail: unknown, responseBody: string, statusText: string) {
    super(typeof detail === 'string' && detail.trim() ? detail : statusText);
    this.name = 'ApiHttpError';
    this.status = status;
    this.detail = detail;
    this.responseBody = responseBody;
  }
}

function responseDetail(body: string): unknown {
  if (!body) return null;
  try {
    const parsed = JSON.parse(body) as { detail?: unknown };
    return parsed.detail ?? parsed;
  } catch {
    return body;
  }
}

function emitSessionExpired(): void {
  window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
}

async function checkedResponse(
  response: Response,
  emitExpired: boolean,
): Promise<{ response: Response; body: string }> {
  if (response.ok) return { response, body: '' };
  const body = await response.text();
  const detail = responseDetail(body);
  if (response.status === 401 && emitExpired) emitSessionExpired();
  throw new ApiHttpError(response.status, detail, body, response.statusText);
}

async function fetchCsrfToken(): Promise<CsrfToken> {
  if (csrfToken) return csrfToken;
  if (csrfRequest) return csrfRequest;

  const requestGeneration = csrfGeneration;
  const pendingRequest = (async () => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    try {
      const response = await fetch('/auth/csrf', {
        method: 'GET',
        cache: 'no-store',
        credentials: 'same-origin',
        signal: controller.signal,
      });
      await checkedResponse(response, true);
      const token = await response.json() as CsrfToken;
      if (!token.csrf_token || !token.header_name) {
        throw new Error('The Identity service returned an invalid CSRF contract.');
      }
      if (requestGeneration !== csrfGeneration) {
        csrfRequest = null;
        return fetchCsrfToken();
      }
      csrfToken = token;
      return token;
    } finally {
      window.clearTimeout(timeout);
    }
  })();
  csrfRequest = pendingRequest;

  try {
    return await pendingRequest;
  } finally {
    if (csrfRequest === pendingRequest) csrfRequest = null;
  }
}

export function invalidateCsrfToken(): void {
  csrfGeneration += 1;
  csrfToken = null;
  csrfRequest = null;
}

export function subscribeToSessionExpired(listener: () => void): () => void {
  window.addEventListener(SESSION_EXPIRED_EVENT, listener);
  return () => window.removeEventListener(SESSION_EXPIRED_EVENT, listener);
}

export async function httpRequest<T>(
  path: string,
  init: RequestInit = {},
  options: RequestOptions = {},
): Promise<T> {
  const method = (init.method ?? 'GET').toUpperCase();
  const requiresCsrf = options.csrf !== false && MUTATION_METHODS.has(method);
  const timeoutMs = options.timeoutMs ?? REQUEST_TIMEOUT_MS;

  const execute = async (retryingCsrf: boolean): Promise<T> => {
    const headers = new Headers(init.headers);
    if (init.body !== undefined && init.body !== null && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }
    if (requiresCsrf) {
      const token = await fetchCsrfToken();
      headers.set(token.header_name, token.csrf_token);
    }

    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(path, {
        ...init,
        method,
        headers,
        cache: 'no-store',
        credentials: 'same-origin',
        signal: controller.signal,
      });
      try {
        await checkedResponse(response, options.emitSessionExpired !== false);
      } catch (cause) {
        if (
          cause instanceof ApiHttpError
          && requiresCsrf
          && !retryingCsrf
          && cause.status === 403
          && cause.detail === 'csrf_validation_failed'
        ) {
          invalidateCsrfToken();
          return execute(true);
        }
        throw cause;
      }
      if (options.expectedStatuses && !options.expectedStatuses.includes(response.status)) {
        const body = await response.text();
        throw new ApiHttpError(response.status, responseDetail(body), body, response.statusText);
      }

      if (response.status === 204) return undefined as T;
      return response.json() as Promise<T>;
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === 'AbortError') {
        throw new Error(`The platform did not respond within ${Math.round(timeoutMs / 1000)} seconds.`);
      }
      throw cause;
    } finally {
      window.clearTimeout(timeout);
    }
  };

  return execute(false);
}
