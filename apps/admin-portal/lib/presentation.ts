import { PlatformApiError, type JsonObject } from './platform-api';

const STATUS_MESSAGE_KEYS: Record<string, string> = {
  active: 'status.active', archived: 'status.archived', attention: 'status.degraded', available: 'status.available',
  blocked: 'status.blocked', canceled: 'status.cancelled', cancelled: 'status.cancelled',
  completed: 'status.completed', configured: 'status.configured',
  configuration_only: 'status.configurationOnly',
  degraded: 'status.degraded', deleted: 'status.deleted', disabled: 'status.disabled', draft: 'status.draft',
  enabled: 'status.enabled', error: 'status.failed',
  expired: 'status.expired', failed: 'status.failed', indexed: 'status.indexed',
  inactive: 'status.inactive',
  legacy_unscoped: 'status.legacyUnscoped', not_configured: 'status.notConfigured',
  not_eligible: 'status.notEligible', not_evaluated: 'status.notEvaluated', not_ready: 'status.notReady',
  pending: 'status.pending', prepared: 'status.ready', processed: 'status.processed',
  processing: 'status.processing', published: 'status.published', ready: 'status.ready',
  recorded: 'status.recorded', registered: 'status.registered', running: 'status.running',
  searchable: 'status.searchable',
  stored: 'status.stored', succeeded: 'status.completed', unavailable: 'status.unavailable',
  unsupported: 'status.unsupported', unverified: 'status.unverified',
  uploaded: 'status.uploaded', verified: 'status.verified',
};

export function productLabel(value: unknown, fallback = '-'): string {
  if (value === true || value === false) return String(value);
  if (value === null || value === undefined || value === '') return fallback;
  const source = String(value).trim();
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(source)) return source;
  if (/^(?:https?:\/\/|\/)/i.test(source)) return source;
  return source;
}

export function localizedProductLabel(
  value: unknown,
  translate: (key: string) => string,
  fallback?: string,
): string {
  if (value === true) return translate('status.ready');
  if (value === false) return translate('status.notEvaluated');
  if (value === null || value === undefined || value === '') return fallback ?? translate('common.notAvailable');
  const source = String(value).trim();
  const key = STATUS_MESSAGE_KEYS[source.toLowerCase()];
  return key ? translate(key) : productLabel(source, fallback ?? translate('common.notAvailable'));
}

export function localizedStatusLabel(
  value: unknown,
  translate: (key: string) => string,
): string {
  if (value === true) return translate('status.ready');
  if (value === false) return translate('status.notReady');
  if (value === null || value === undefined || value === '') return translate('status.notEvaluated');
  const key = STATUS_MESSAGE_KEYS[String(value).trim().toLowerCase()];
  return translate(key ?? 'status.unknown');
}

export function localizedApiError(
  cause: unknown,
  translate: (key: string) => string,
  fallbackKey: string,
): string {
  if (!(cause instanceof PlatformApiError)) return translate(fallbackKey);
  if (cause.status === 401) return translate('errors.unauthorized');
  if (cause.status === 403) return translate('errors.forbidden');
  if (cause.status === 404) return translate('errors.notFound');
  if (cause.status === 409) return translate('errors.conflict');
  if (cause.status === 422) return translate('errors.validation');
  if (cause.status >= 500) return translate('errors.temporary');
  return translate(fallbackKey);
}

export function localizedAssistantAvailability(
  availability: JsonObject | null | undefined,
  assistantStatus: unknown,
  translate: (key: string) => string,
): { title: string; description: string; runtimeAvailable: boolean } {
  const evidence = availability ?? {};
  const enabled = evidence.assistant_enabled === true
    || (evidence.assistant_enabled === undefined
      && ['active', 'prepared'].includes(String(assistantStatus ?? '').toLowerCase()));
  const authorized = evidence.organization_access_authorized !== false;
  const grounded = evidence.grounded_answers_available === true;
  const generation = evidence.ai_generation_available === true;
  const providerConfigured = evidence.ai_provider_configured === true;
  const providerRequired = evidence.ai_provider_required === true;
  const deterministic = evidence.operation_without_llm_available === true;
  const searchRequested = evidence.enterprise_search_requested === true;
  const searchAvailable = evidence.enterprise_search_available === true;

  if (!authorized) {
    return {
      title: translate('ask.availability.accessRequired'),
      description: translate('ask.availability.accessRequiredHelp'),
      runtimeAvailable: false,
    };
  }
  if (!enabled) {
    return {
      title: translate('ask.availability.disabled'),
      description: translate('ask.availability.disabledHelp'),
      runtimeAvailable: false,
    };
  }
  if (providerRequired && !generation) {
    return {
      title: translate(providerConfigured
        ? 'ask.availability.generationUnavailable'
        : 'ask.availability.generationNotConfigured'),
      description: translate(providerConfigured
        ? 'ask.availability.generationUnavailableRequiredHelp'
        : 'ask.availability.generationNotConfiguredRequiredHelp'),
      runtimeAvailable: false,
    };
  }
  if (grounded && generation) {
    return {
      title: translate('ask.availability.groundedAndGenerative'),
      description: translate('ask.availability.groundedAndGenerativeHelp'),
      runtimeAvailable: true,
    };
  }
  if (grounded) {
    return {
      title: translate('ask.availability.groundedDeterministic'),
      description: translate(providerConfigured
        ? 'ask.availability.groundedGenerationUnavailableHelp'
        : 'ask.availability.groundedGenerationNotConfiguredHelp'),
      runtimeAvailable: true,
    };
  }
  if (generation) {
    return {
      title: translate('ask.availability.generativeWithoutSources'),
      description: translate('ask.availability.generativeWithoutSourcesHelp'),
      runtimeAvailable: true,
    };
  }
  if (deterministic) {
    return {
      title: translate('ask.availability.deterministic'),
      description: translate(searchRequested && !searchAvailable
        ? 'ask.availability.deterministicNoSourcesHelp'
        : 'ask.availability.deterministicHelp'),
      runtimeAvailable: true,
    };
  }
  return {
    title: translate(providerConfigured
      ? 'ask.availability.generationUnavailable'
      : 'ask.availability.unavailable'),
    description: translate(providerConfigured
      ? 'ask.availability.generationUnavailableHelp'
      : 'ask.availability.unavailableHelp'),
    runtimeAvailable: false,
  };
}

export function productStatus(value: unknown): 'ready' | 'attention' | 'neutral' {
  if (value === true) return 'ready';
  const normalized = String(value ?? '').toLowerCase();
  if (['active', 'available', 'completed', 'configured', 'enabled', 'indexed', 'prepared', 'published', 'ready', 'searchable', 'succeeded'].includes(normalized)) return 'ready';
  if (['blocked', 'degraded', 'failed', 'error', 'unavailable'].includes(normalized)) return 'attention';
  return 'neutral';
}

export function issueMessage(issue: JsonObject, fallback = '-'): string {
  return String(issue.message ?? issue.reason ?? issue.label ?? issue.code ?? fallback);
}
