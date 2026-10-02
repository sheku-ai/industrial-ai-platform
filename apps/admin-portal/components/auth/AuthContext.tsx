'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import { authApi, type AuthPrincipal } from '../../lib/auth-api';
import { ApiHttpError, invalidateCsrfToken, subscribeToSessionExpired } from '../../lib/http-client';

const ORGANIZATION_STORAGE_KEY = 'industrial-ai-platform.organization-id';
const ORGANIZATION_SESSION_KEY = 'industrial-ai-platform.organization-selection-confirmed';

export type AuthStatus = 'checking' | 'authenticated' | 'unauthenticated' | 'unavailable';

type AuthContextValue = {
  status: AuthStatus;
  principal: AuthPrincipal | null;
  checkSession: () => Promise<void>;
  login: (email: string, password: string, rememberMe?: boolean) => Promise<void>;
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function clearAuthenticatedWorkspace(): void {
  invalidateCsrfToken();
  window.localStorage.removeItem(ORGANIZATION_STORAGE_KEY);
  window.sessionStorage.removeItem(ORGANIZATION_SESSION_KEY);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('checking');
  const [principal, setPrincipal] = useState<AuthPrincipal | null>(null);

  const markUnauthenticated = useCallback(() => {
    clearAuthenticatedWorkspace();
    setPrincipal(null);
    setStatus('unauthenticated');
  }, []);

  const checkSession = useCallback(async () => {
    setStatus('checking');
    try {
      const authenticatedPrincipal = await authApi.me();
      setPrincipal(authenticatedPrincipal);
      setStatus('authenticated');
    } catch (cause) {
      if (cause instanceof ApiHttpError && cause.status === 401) {
        markUnauthenticated();
        return;
      }
      setPrincipal(null);
      setStatus('unavailable');
    }
  }, [markUnauthenticated]);

  useEffect(() => {
    void checkSession();
  }, [checkSession]);

  useEffect(
    () => subscribeToSessionExpired(markUnauthenticated),
    [markUnauthenticated],
  );

  const login = useCallback(async (email: string, password: string, rememberMe = false) => {
    const authenticatedPrincipal = await authApi.login(email, password, rememberMe);
    setPrincipal(authenticatedPrincipal);
    setStatus('authenticated');
  }, []);

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
      markUnauthenticated();
    } catch (cause) {
      if (cause instanceof ApiHttpError && cause.status === 401) {
        markUnauthenticated();
        return;
      }
      throw cause;
    }
  }, [markUnauthenticated]);

  const changePassword = useCallback(async (currentPassword: string, newPassword: string) => {
    await authApi.changePassword(currentPassword, newPassword);
    markUnauthenticated();
  }, [markUnauthenticated]);

  const value = useMemo<AuthContextValue>(() => ({
    status,
    principal,
    checkSession,
    changePassword,
    login,
    logout,
  }), [changePassword, checkSession, login, logout, principal, status]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within AuthProvider.');
  return context;
}
