const configuredApiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.trim() ?? '';

function normalizeApiBaseUrl(value: string): string {
  if (!value || value === '/') return '';
  const normalized = value.replace(/\/+$/, '');
  return normalized.endsWith('/api') ? normalized.slice(0, -4) : normalized;
}

export const API_BASE_URL = normalizeApiBaseUrl(configuredApiBaseUrl);

export function resolveApiUrl(path: string): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${API_BASE_URL}${normalizedPath}`;
}
