import { httpRequest } from './http-client';

export type InstallationState = 'UNCONFIGURED' | 'IN_PROGRESS' | 'READY_TO_COMPLETE' | 'COMPLETED';

export type InstallationStatus = {
  state: InstallationState;
  token_authorized: boolean;
  setup_available: boolean;
  setup_schema_version: number;
  steps: Record<string, boolean>;
  next_step: string | null;
  ready_to_complete: boolean;
  details: Record<string, Record<string, unknown>>;
  password_policy: {
    min_length: number;
    max_length: number;
    block_context: boolean;
    block_common: boolean;
  };
};

function tokenHeaders(token?: string): HeadersInit | undefined {
  return token ? { 'X-SHEKU-Setup-Token': token } : undefined;
}

export const installationSetupApi = {
  status: (token?: string) => httpRequest<InstallationStatus>(
    '/setup/status',
    { headers: tokenHeaders(token) },
    { csrf: false, emitSessionExpired: false },
  ),
  organization: (token: string, payload: { name: string; slug: string }) => httpRequest<InstallationStatus>(
    '/setup/organization',
    { method: 'PUT', body: JSON.stringify(payload), headers: tokenHeaders(token) },
    { csrf: false, emitSessionExpired: false },
  ),
  administrator: (
    token: string,
    payload: { email: string; display_name: string | null; password: string },
  ) => httpRequest<InstallationStatus>(
    '/setup/administrator',
    { method: 'PUT', body: JSON.stringify(payload), headers: tokenHeaders(token) },
    { csrf: false, emitSessionExpired: false },
  ),
  preferences: (token: string, payload: { language: string; timezone: string }) => httpRequest<InstallationStatus>(
    '/setup/preferences',
    { method: 'PUT', body: JSON.stringify(payload), headers: tokenHeaders(token) },
    { csrf: false, emitSessionExpired: false },
  ),
  complete: (token: string) => httpRequest<InstallationStatus>(
    '/setup/complete',
    { method: 'POST', body: '{}', headers: tokenHeaders(token) },
    { csrf: false, emitSessionExpired: false },
  ),
};
