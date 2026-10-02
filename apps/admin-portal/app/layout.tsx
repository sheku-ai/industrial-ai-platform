import './globals.css';
import { cookies } from 'next/headers';

import { AppShell } from '../components/layout/AppShell';
import { loadCatalog } from '../i18n/catalogs';
import {
  defaultLocale,
  isSupportedLocale,
  localeCookieKey,
  localeDirection,
  resolveLocale,
} from '../i18n/config';

export const metadata = {
  title: 'SHEKU',
  description: 'SHEKU Admin Portal',
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const cookieStore = await cookies();
  const persistedLocale = cookieStore.get(localeCookieKey)?.value;
  const requestedLocale = isSupportedLocale(persistedLocale)
    ? resolveLocale([persistedLocale])
    : defaultLocale;
  const fallback = await loadCatalog(defaultLocale);
  const initial = requestedLocale === defaultLocale
    ? fallback
    : await loadCatalog(requestedLocale);

  return (
    <html dir={localeDirection(initial.locale)} lang={initial.locale}>
      <body>
        <AppShell
          fallbackCatalog={fallback.catalog}
          initialCatalog={initial.catalog}
          initialLocale={initial.locale}
        >
          {children}
        </AppShell>
      </body>
    </html>
  );
}
