import 'server-only';

import type { NextRequest } from 'next/server';

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

type StreamingRequestInit = RequestInit & {
  duplex?: 'half';
};

const REQUEST_HOP_BY_HOP_HEADERS = new Set([
  'connection',
  'content-length',
  'host',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
]);

const RESPONSE_TRANSPORT_HEADERS = new Set([
  'connection',
  'content-encoding',
  'content-length',
  'keep-alive',
  'transfer-encoding',
]);

function internalApiBaseUrl(): string | null {
  const configured = process.env.API_INTERNAL_BASE_URL?.trim();
  return configured ? configured.replace(/\/+$/, '').replace(/\/api$/, '') : null;
}

function forwardedHeaders(request: NextRequest): Headers {
  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!REQUEST_HOP_BY_HOP_HEADERS.has(key.toLowerCase())) headers.set(key, value);
  });
  headers.set('X-Forwarded-Host', request.headers.get('host') ?? request.nextUrl.host);
  headers.set('X-Forwarded-Proto', request.nextUrl.protocol.replace(':', ''));
  return headers;
}

function forwardedResponseHeaders(upstream: Response): Headers {
  const headers = new Headers(upstream.headers);
  for (const header of RESPONSE_TRANSPORT_HEADERS) headers.delete(header);

  const upstreamHeaders = upstream.headers as Headers & { getSetCookie?: () => string[] };
  const setCookies = upstreamHeaders.getSetCookie?.();
  if (setCookies?.length) {
    headers.delete('set-cookie');
    for (const value of setCookies) headers.append('set-cookie', value);
  }
  headers.set('Cache-Control', 'no-store');
  return headers;
}

export function createApiProxy(prefix: 'api' | 'auth' | 'setup') {
  return async function proxy(request: NextRequest, context: RouteContext): Promise<Response> {
    const apiBaseUrl = internalApiBaseUrl();
    if (!apiBaseUrl) {
      return Response.json(
        { detail: 'API_INTERNAL_BASE_URL is required for same-origin Portal API proxying.' },
        { status: 502, headers: { 'Cache-Control': 'no-store' } },
      );
    }

    const { path } = await context.params;
    const target = new URL(
      `${apiBaseUrl}/${prefix}/${path.map((segment) => encodeURIComponent(segment)).join('/')}`,
    );
    target.search = request.nextUrl.search;
    const hasBody = request.method !== 'GET' && request.method !== 'HEAD';
    const init: StreamingRequestInit = {
      method: request.method,
      headers: forwardedHeaders(request),
      body: hasBody ? request.body : undefined,
      cache: 'no-store',
      redirect: 'manual',
      duplex: hasBody ? 'half' : undefined,
    };
    const upstream = await fetch(target, init);
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: forwardedResponseHeaders(upstream),
    });
  };
}
