'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import {
  isSelectableOrganization,
  isValidationOrganization,
  listOrganizations,
  PlatformApiError,
  sortOrganizations,
  type PlatformEntity,
} from '../../lib/platform-api';
import {
  getAssistantWorkspaceCapabilities,
  type AssistantWorkspaceCapabilities,
} from '../../lib/assistant-workspace-api';
import { getOperationsCenterRuntime } from '../../lib/operations-center-api';
import { getProductNavigationCapabilities, type ProductNavigationCapabilities } from '../../lib/platform-dashboard-api';
import { localizedApiError } from '../../lib/presentation';
import { useI18n } from '../../i18n/I18nProvider';
import { useAuth } from '../auth/AuthContext';

const STORAGE_KEY = 'industrial-ai-platform.organization-id';
const SESSION_SELECTION_KEY = 'industrial-ai-platform.organization-selection-confirmed';

function platformOperationsCapabilities(
  read: boolean,
  administer: boolean,
): ProductNavigationCapabilities {
  return {
    organization_id: null,
    documents: { visible: false, action_available: false },
    search: { visible: false, action_available: false },
    assistant: { visible: false, action_available: false },
    ai_configuration: {
      visible: false,
      administer_providers: false,
      administer_models: false,
      validate: false,
    },
    platform: {
      operations: { visible: read, action_available: administer },
      scheduler: { visible: administer, action_available: administer },
      release_readiness: { visible: false, action_available: false },
    },
  };
}

function withPlatformOperationsAuthorization(
  capabilities: ProductNavigationCapabilities,
  read: boolean,
  administer: boolean,
): ProductNavigationCapabilities {
  return {
    ...capabilities,
    platform: {
      ...capabilities.platform,
      operations: { visible: read, action_available: administer },
    },
  };
}

type OrganizationContextValue = {
  organizations: PlatformEntity[];
  excludedOrganizations: PlatformEntity[];
  organization: PlatformEntity | null;
  loading: boolean;
  slowLoading: boolean;
  error: string | null;
  errorStatus: number | null;
  assistantCapabilities: AssistantWorkspaceCapabilities | null;
  capabilitiesLoading: boolean;
  capabilitiesResolved: boolean;
  capabilitiesError: string | null;
  capabilitiesErrorStatus: number | null;
  navigationCapabilities: ProductNavigationCapabilities | null;
  selectOrganization: (organizationId: string) => void;
  refreshOrganizations: () => Promise<void>;
  refreshCapabilities: () => Promise<void>;
};

const OrganizationContext = createContext<OrganizationContextValue | null>(null);

export function OrganizationProvider({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const { principal } = useAuth();
  const membershipOrganizationIds = useMemo(
    () => new Set(
      principal?.memberships
        .filter((membership) => membership.status === 'active')
        .map((membership) => membership.organization_id) ?? [],
    ),
    [principal],
  );
  const [organizations, setOrganizations] = useState<PlatformEntity[]>([]);
  const [excludedOrganizations, setExcludedOrganizations] = useState<PlatformEntity[]>([]);
  const [organization, setOrganization] = useState<PlatformEntity | null>(null);
  const [loading, setLoading] = useState(true);
  const [slowLoading, setSlowLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  const [assistantCapabilities, setAssistantCapabilities] = useState<AssistantWorkspaceCapabilities | null>(null);
  const [capabilitiesLoading, setCapabilitiesLoading] = useState(false);
  const [capabilitiesResolved, setCapabilitiesResolved] = useState(false);
  const [capabilitiesError, setCapabilitiesError] = useState<string | null>(null);
  const [capabilitiesErrorStatus, setCapabilitiesErrorStatus] = useState<number | null>(null);
  const [navigationCapabilities, setNavigationCapabilities] = useState<ProductNavigationCapabilities | null>(null);
  const capabilityRequestRef = useRef(0);

  const refreshOrganizations = useCallback(async () => {
    setLoading(true);
    setError(null);
    setErrorStatus(null);

    try {
      const available = await listOrganizations();
      const authorized = available.filter((organization) => membershipOrganizationIds.has(organization.id));
      const selectable = sortOrganizations(authorized.filter(isSelectableOrganization));
      const excluded = sortOrganizations(authorized.filter(isValidationOrganization));
      setOrganizations(selectable);
      setExcludedOrganizations(excluded);

      const storedId = window.localStorage.getItem(STORAGE_KEY);
      const sessionSelectionConfirmed = window.sessionStorage.getItem(SESSION_SELECTION_KEY) === storedId;
      const selected = selectable.length === 1
        ? selectable[0]
        : storedId && sessionSelectionConfirmed
          ? selectable.find((candidate) => candidate.id === storedId) ?? null
          : null;

      setOrganization((current) => selectable.find((candidate) => candidate.id === current?.id) ?? selected);
      if (selected && selectable.length === 1) {
        window.localStorage.setItem(STORAGE_KEY, selected.id);
        window.sessionStorage.setItem(SESSION_SELECTION_KEY, selected.id);
      } else if (storedId && !selectable.some((candidate) => candidate.id === storedId)) {
        window.localStorage.removeItem(STORAGE_KEY);
        window.sessionStorage.removeItem(SESSION_SELECTION_KEY);
      }
    } catch (cause) {
      setErrorStatus(cause instanceof PlatformApiError ? cause.status : null);
      setError(localizedApiError(cause, t, 'feedback.organizationsUnavailable'));
    } finally {
      setLoading(false);
    }
  }, [membershipOrganizationIds, t]);

  useEffect(() => {
    void refreshOrganizations();
  }, [refreshOrganizations]);

  const refreshCapabilities = useCallback(async () => {
    const requestId = ++capabilityRequestRef.current;
    setCapabilitiesLoading(true);
    setCapabilitiesError(null);
    setCapabilitiesErrorStatus(null);
    if (!organization) {
      setAssistantCapabilities(null);
      try {
        const operationsRuntime = await getOperationsCenterRuntime();
        if (requestId !== capabilityRequestRef.current) return;
        setNavigationCapabilities(platformOperationsCapabilities(
          operationsRuntime.authorization['platform.operations:read'],
          operationsRuntime.authorization['platform.operations:administer'],
        ));
        setCapabilitiesResolved(true);
      } catch (cause) {
        if (requestId !== capabilityRequestRef.current) return;
        if (cause instanceof PlatformApiError && cause.status === 403) {
          setNavigationCapabilities(platformOperationsCapabilities(false, false));
          setCapabilitiesResolved(true);
        } else {
          setNavigationCapabilities(null);
          setCapabilitiesResolved(false);
          setCapabilitiesErrorStatus(cause instanceof PlatformApiError ? cause.status : null);
          setCapabilitiesError(localizedApiError(cause, t, 'feedback.accessEvaluationFailed'));
        }
      } finally {
        if (requestId === capabilityRequestRef.current) setCapabilitiesLoading(false);
      }
      return;
    }
    try {
      const [assistantResult, navigationResult, operationsResult] = await Promise.allSettled([
        getAssistantWorkspaceCapabilities(organization.id),
        getProductNavigationCapabilities(),
        getOperationsCenterRuntime(),
      ]);
      if (requestId !== capabilityRequestRef.current) return;
      setAssistantCapabilities(
        assistantResult.status === 'fulfilled' ? assistantResult.value : null,
      );
      const operationsDenied = operationsResult.status === 'rejected'
        && operationsResult.reason instanceof PlatformApiError
        && operationsResult.reason.status === 403;
      const operationsAuthorization = operationsResult.status === 'fulfilled'
        ? operationsResult.value.authorization
        : null;
      setNavigationCapabilities(navigationResult.status === 'fulfilled'
        ? withPlatformOperationsAuthorization(
          navigationResult.value,
          operationsAuthorization?.['platform.operations:read'] ?? false,
          operationsAuthorization?.['platform.operations:administer'] ?? false,
        )
        : null);
      setCapabilitiesResolved(
        navigationResult.status === 'fulfilled'
        && (operationsResult.status === 'fulfilled' || operationsDenied),
      );
      const rejected = [
        assistantResult,
        navigationResult,
        ...(operationsDenied ? [] : [operationsResult]),
      ].find(
        (result) => result.status === 'rejected',
      );
      if (rejected?.status === 'rejected') {
        setCapabilitiesErrorStatus(
          rejected.reason instanceof PlatformApiError ? rejected.reason.status : null,
        );
        setCapabilitiesError(
          localizedApiError(rejected.reason, t, 'feedback.accessEvaluationFailed'),
        );
      }
    } finally {
      if (requestId === capabilityRequestRef.current) setCapabilitiesLoading(false);
    }
  }, [organization, t]);

  useEffect(() => {
    void refreshCapabilities();
  }, [refreshCapabilities]);

  useEffect(() => {
    if (!loading && !capabilitiesLoading) {
      setSlowLoading(false);
      return;
    }
    const timer = window.setTimeout(() => setSlowLoading(true), 1500);
    return () => window.clearTimeout(timer);
  }, [capabilitiesLoading, loading]);

  const selectOrganization = useCallback(
    (organizationId: string) => {
      const selected = organizations.find((candidate) => candidate.id === organizationId) ?? null;
      setOrganization(selected);
      setCapabilitiesResolved(false);
      setCapabilitiesError(null);
      setCapabilitiesErrorStatus(null);

      if (selected) {
        window.localStorage.setItem(STORAGE_KEY, selected.id);
        window.sessionStorage.setItem(SESSION_SELECTION_KEY, selected.id);
      } else {
        window.localStorage.removeItem(STORAGE_KEY);
        window.sessionStorage.removeItem(SESSION_SELECTION_KEY);
      }
    },
    [organizations],
  );

  const value = useMemo<OrganizationContextValue>(
    () => ({
      organizations,
      excludedOrganizations,
      organization,
      loading,
      slowLoading,
      error,
      errorStatus,
      assistantCapabilities,
      capabilitiesLoading,
      capabilitiesResolved,
      capabilitiesError,
      capabilitiesErrorStatus,
      navigationCapabilities,
      selectOrganization,
      refreshOrganizations,
      refreshCapabilities,
    }),
    [
      organizations,
      excludedOrganizations,
      organization,
      loading,
      slowLoading,
      error,
      errorStatus,
      assistantCapabilities,
      capabilitiesLoading,
      capabilitiesResolved,
      capabilitiesError,
      capabilitiesErrorStatus,
      navigationCapabilities,
      selectOrganization,
      refreshOrganizations,
      refreshCapabilities,
    ],
  );

  return <OrganizationContext.Provider value={value}>{children}</OrganizationContext.Provider>;
}

export function useOrganization(): OrganizationContextValue {
  const context = useContext(OrganizationContext);
  if (!context) {
    throw new Error('useOrganization must be used within OrganizationProvider.');
  }
  return context;
}
