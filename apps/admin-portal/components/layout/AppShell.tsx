import { I18nProvider } from '../../i18n/I18nProvider';
import type { Catalog } from '../../i18n/catalogs';
import type { SupportedLocale } from '../../i18n/config';
import { AuthBoundary } from '../auth/AuthBoundary';
import { AuthProvider } from '../auth/AuthContext';
import { MySessions } from '../auth/MySessions';
import { OrganizationProvider } from '../organization/OrganizationContext';
import { OrganizationSelector } from '../organization/OrganizationSelector';
import { InstallationBoundary } from '../setup/InstallationBoundary';
import { HashScrollRestorer } from './HashScrollRestorer';
import { LocalizedText } from './LocalizedText';
import { OrganizationScope } from './OrganizationScope';
import { Sidebar } from './Sidebar';

type AppShellProps = {
  children: React.ReactNode;
  fallbackCatalog: Catalog;
  initialCatalog: Catalog;
  initialLocale: SupportedLocale;
};

export function AppShell({
  children,
  fallbackCatalog,
  initialCatalog,
  initialLocale,
}: AppShellProps) {
  return (
    <I18nProvider
      fallbackCatalog={fallbackCatalog}
      initialCatalog={initialCatalog}
      initialLocale={initialLocale}
    >
      <InstallationBoundary
        application={(
          <AuthProvider>
            <AuthBoundary
              workspace={(
                <OrganizationProvider>
                  <a className="skip-link" href="#main-content"><LocalizedText id="shell.skipToContent" /></a>
                  <div className="app-shell">
                    <Sidebar />
                    <main className="main" id="main-content">
                      <HashScrollRestorer />
                      <OrganizationSelector />
                      <MySessions />
                      <OrganizationScope>{children}</OrganizationScope>
                    </main>
                  </div>
                </OrganizationProvider>
              )}
            >
              {children}
            </AuthBoundary>
          </AuthProvider>
        )}
      >
        {children}
      </InstallationBoundary>
    </I18nProvider>
  );
}
