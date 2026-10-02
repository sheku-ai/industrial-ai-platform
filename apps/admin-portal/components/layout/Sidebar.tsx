'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState } from 'react';

import { useI18n } from '../../i18n/I18nProvider';
import { platformCapabilityAvailable, type PlatformCapabilityKey } from '../../lib/platform-dashboard-api';
import { useAuth } from '../auth/AuthContext';
import { useOrganization } from '../organization/OrganizationContext';

type NavigationItem = {
  labelKey: string;
  href: string;
  description?: string;
  assistantCapability?: 'workspace' | 'chat' | 'conversations';
  productCapability?: 'documents' | 'search' | 'ai_configuration';
  platformCapability?: PlatformCapabilityKey;
};

type NavigationGroup = {
  labelKey: string;
  items: NavigationItem[];
};

const navigationGroups: NavigationGroup[] = [
  {
    labelKey: 'navigation.dailyWork',
    items: [
      { labelKey: 'navigation.home', href: '/' },
      { labelKey: 'navigation.documents', href: '/documents', productCapability: 'documents' },
      { labelKey: 'navigation.search', href: '/search', productCapability: 'search' },
      { labelKey: 'navigation.askAI', href: '/ask', assistantCapability: 'workspace' },
    ],
  },
  {
    labelKey: 'navigation.manage',
    items: [
      { labelKey: 'navigation.knowledge', href: '/knowledge' },
      { labelKey: 'navigation.reports', href: '/analytics' },
      { labelKey: 'navigation.integrations', href: '/integrations' },
    ],
  },
  {
    labelKey: 'navigation.administration',
    items: [
      { labelKey: 'navigation.organization', href: '/organization' },
      { labelKey: 'navigation.usersAccess', href: '/security' },
      { labelKey: 'navigation.aiConfiguration', href: '/ai', productCapability: 'ai_configuration' },
    ],
  },
  {
    labelKey: 'navigation.platform',
    items: [
      { labelKey: 'navigation.operations', href: '/operations', platformCapability: 'operations' },
      { labelKey: 'navigation.governance', href: '/governance' },
      { labelKey: 'navigation.releaseReadiness', href: '/production', platformCapability: 'release_readiness' },
      { labelKey: 'navigation.capabilityInventory', href: '/workflows' },
    ],
  },
];

function isCurrentPath(pathname: string, href: string): boolean {
  const path = href.split('#')[0];
  return path === '/' ? pathname === '/' : pathname === path || pathname.startsWith(`${path}/`);
}

export function Sidebar() {
  const pathname = usePathname();
  const { t } = useI18n();
  const { principal, logout } = useAuth();
  const { assistantCapabilities, capabilitiesLoading, capabilitiesResolved, navigationCapabilities, organization } = useOrganization();
  const [open, setOpen] = useState(false);
  const [logoutPending, setLogoutPending] = useState(false);
  const [logoutError, setLogoutError] = useState(false);

  const signOut = async () => {
    setLogoutPending(true);
    setLogoutError(false);
    try {
      await logout();
    } catch {
      setLogoutError(true);
    } finally {
      setLogoutPending(false);
    }
  };

  return (
    <>
      <button
        aria-controls="platform-navigation"
        aria-expanded={open}
        aria-label={t(open ? 'navigation.closeNavigation' : 'navigation.openNavigation')}
        className="navigation-toggle"
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        <span aria-hidden="true">{open ? '×' : '☰'}</span>
      </button>
      {open ? <button aria-label={t('navigation.dismissOverlay')} className="navigation-scrim" onClick={() => setOpen(false)} type="button" /> : null}
      <aside className={`sidebar${open ? ' is-open' : ''}`} id="platform-navigation">
        <div className="brand-block">
          <Link className="brand" href="/" onClick={() => setOpen(false)}>SHEKU</Link>
        </div>
        <nav aria-label={t('navigation.productNavigation')} className="nav">
          {navigationGroups.map((group) => (
            <section className="nav-group" key={group.labelKey}>
              <h2 className="nav-group-label">{t(group.labelKey)}</h2>
              <div className="nav-group-items">
                {group.items.map((item) => {
                  const current = isCurrentPath(pathname, item.href);
                  const capabilityAvailable = !item.assistantCapability || (
                    item.assistantCapability === 'workspace'
                      ? assistantCapabilities?.workspace_available
                      : item.assistantCapability === 'chat'
                        ? assistantCapabilities?.chat_available
                        : assistantCapabilities?.conversations_available
                  );
                  const productCapabilityAvailable = !item.productCapability || navigationCapabilities?.[item.productCapability]?.visible;
                  const globalCapabilityAvailable = !item.platformCapability
                    || platformCapabilityAvailable(navigationCapabilities, item.platformCapability);
                  if (
                    item.productCapability === 'ai_configuration'
                    && (!capabilitiesResolved || capabilitiesLoading)
                  ) {
                    return (
                      <span
                        aria-disabled="true"
                        className="nav-link is-disabled"
                        key={item.href}
                        title={t('dynamic.accessEvaluating')}
                      >
                        {t(item.labelKey)}
                      </span>
                    );
                  }
                  if (item.productCapability && capabilitiesResolved && !capabilitiesLoading && !productCapabilityAvailable) return null;
                  if (item.platformCapability && (!capabilitiesResolved || capabilitiesLoading)) {
                    return (
                      <span
                        aria-disabled="true"
                        className="nav-link is-disabled"
                        key={item.href}
                        title={t('dynamic.accessEvaluating')}
                      >
                        {t(item.labelKey)}
                      </span>
                    );
                  }
                  if (item.platformCapability && !globalCapabilityAvailable) {
                    const explanation = t('navigation.platformPermissionRequired');
                    return (
                      <span
                        aria-disabled="true"
                        aria-label={`${t(item.labelKey)}. ${explanation}`}
                        className="nav-link is-disabled is-restricted"
                        key={item.href}
                        role="link"
                        tabIndex={0}
                        title={explanation}
                      >
                        <span aria-hidden="true" className="nav-restricted-lock">
                          <svg viewBox="0 0 16 16">
                            <path d="M4.5 7V5a3.5 3.5 0 0 1 7 0v2h.5a1 1 0 0 1 1 1v6H3V8a1 1 0 0 1 1-1h.5Zm1.5 0h4V5a2 2 0 0 0-4 0v2Z" />
                          </svg>
                        </span>
                        <span className="nav-restricted-copy">
                          <span>{t(item.labelKey)}</span>
                          <small>{explanation}</small>
                        </span>
                      </span>
                    );
                  }
                  if (item.assistantCapability && capabilitiesResolved && !capabilitiesLoading && !capabilityAvailable) {
                    const explanation = organization
                      ? t('navigation.assistantPermissionRequired')
                      : t('navigation.selectOrganizationForAssistant');
                    return (
                      <span
                        aria-disabled="true"
                        className="nav-link is-disabled"
                        key={item.href}
                        title={explanation}
                      >
                        {t(item.labelKey)}
                      </span>
                    );
                  }
                  return (
                    <Link
                      aria-current={current ? 'page' : undefined}
                      className={`nav-link${current ? ' is-active' : ''}`}
                      href={item.href}
                      key={item.href}
                      onClick={() => setOpen(false)}
                    >
                      {t(item.labelKey)}
                    </Link>
                  );
                })}
              </div>
            </section>
          ))}
        </nav>
        <div className="sidebar-identity">
          <span>{t('auth.signedInAs')}</span>
          <strong>{principal?.user.display_name || principal?.user.email}</strong>
          {principal?.user.display_name ? <small>{principal.user.email}</small> : null}
          <button
            className="sidebar-logout"
            disabled={logoutPending}
            onClick={() => void signOut()}
            type="button"
          >
            {t(logoutPending ? 'auth.signingOut' : 'auth.signOut')}
          </button>
          {logoutError ? <small className="sidebar-logout-error" role="alert">{t('auth.logoutUnavailable')}</small> : null}
        </div>
        <div className="sidebar-footer">
          <span>v1.6.0 · {t('navigation.preProduction')}</span>
          <span>{t('navigation.aiOptional')}</span>
        </div>
      </aside>
    </>
  );
}
