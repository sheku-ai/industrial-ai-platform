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
  loadCatalog,
  seedCatalog,
  type Catalog,
  type CatalogValue,
  type LoadedCatalog,
  type PluralMessage,
} from './catalogs';
import {
  defaultLocale,
  isSupportedLocale,
  localeCookieKey,
  localeCookieMaxAge,
  localeDirection,
  localeStorageKey,
  resolveLocale,
  type SupportedLocale,
} from './config';

type InterpolationValues = Record<string, string | number | boolean | null | undefined>;

type I18nContextValue = {
  locale: SupportedLocale;
  dir: 'ltr' | 'rtl';
  setLocale: (locale: SupportedLocale) => void;
  t: (key: string, values?: InterpolationValues) => string;
  number: (value: number, options?: Intl.NumberFormatOptions) => string;
  percent: (value: number, options?: Intl.NumberFormatOptions) => string;
  date: (value: string | number | Date | null | undefined, options?: Intl.DateTimeFormatOptions) => string;
  time: (value: string | number | Date | null | undefined, options?: Intl.DateTimeFormatOptions) => string;
  duration: (milliseconds: number) => string;
};

const I18nContext = createContext<I18nContextValue | null>(null);

function catalogValue(catalog: Catalog, key: string): CatalogValue | undefined {
  let current: CatalogValue = catalog;
  for (const segment of key.split('.')) {
    if (!current || typeof current !== 'object' || isPluralMessage(current)) return undefined;
    current = (current as Catalog)[segment];
  }
  return current;
}

function isPluralMessage(value: CatalogValue): value is PluralMessage {
  return Boolean(value && typeof value === 'object' && typeof (value as { other?: unknown }).other === 'string');
}

function interpolate(template: string, values: InterpolationValues): string {
  return template.replace(/\{([a-zA-Z0-9_]+)\}/g, (match, name: string) => {
    const value = values[name];
    return value === null || value === undefined ? match : String(value);
  });
}

function selectMessage(value: CatalogValue | undefined, locale: SupportedLocale, values: InterpolationValues): string | null {
  if (typeof value === 'string') return value;
  if (!value || !isPluralMessage(value)) return null;
  const count = Number(values.count ?? 0);
  const category = new Intl.PluralRules(locale).select(count);
  return value[category] ?? value.other;
}

function validDate(value: string | number | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === '') return null;
  const parsed = value instanceof Date ? value : new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function persistLocale(locale: SupportedLocale): void {
  window.localStorage.setItem(localeStorageKey, locale);
  document.cookie = `${localeCookieKey}=${encodeURIComponent(locale)}; Path=/; Max-Age=${localeCookieMaxAge}; SameSite=Lax`;
}

type I18nProviderProps = {
  children: ReactNode;
  fallbackCatalog: Catalog;
  initialCatalog: Catalog;
  initialLocale: SupportedLocale;
};

export function I18nProvider({
  children,
  fallbackCatalog,
  initialCatalog,
  initialLocale,
}: I18nProviderProps) {
  const [locale, updateLocale] = useState<SupportedLocale>(initialLocale);
  const [selectedCatalog, setSelectedCatalog] = useState<Catalog>(() => {
    seedCatalog(defaultLocale, fallbackCatalog);
    seedCatalog(initialLocale, initialCatalog);
    return initialCatalog;
  });
  const requestVersion = useRef(0);

  const activateLocale = useCallback(async (requestedLocale: unknown) => {
    const requested = isSupportedLocale(requestedLocale) ? resolveLocale([requestedLocale]) : defaultLocale;
    const version = ++requestVersion.current;
    persistLocale(requested);
    let loaded: LoadedCatalog;
    try {
      loaded = await loadCatalog(requested);
    } catch {
      loaded = { catalog: fallbackCatalog, locale: defaultLocale };
    }
    if (version !== requestVersion.current) return;
    setSelectedCatalog(loaded.catalog);
    updateLocale(loaded.locale);
    persistLocale(loaded.locale);
  }, [fallbackCatalog]);

  useEffect(() => {
    const saved = window.localStorage.getItem(localeStorageKey);
    const persisted = isSupportedLocale(saved) ? resolveLocale([saved]) : null;
    const resolved = resolveLocale([persisted, initialLocale]);
    if (resolved === locale) {
      persistLocale(locale);
      return;
    }
    void activateLocale(resolved);
  }, [activateLocale, initialLocale, locale]);

  useEffect(() => {
    document.documentElement.lang = locale;
    document.documentElement.dir = localeDirection(locale);
  }, [locale]);

  const setLocale = useCallback((nextLocale: SupportedLocale) => {
    void activateLocale(nextLocale);
  }, [activateLocale]);

  const t = useCallback((key: string, values: InterpolationValues = {}) => {
    const selected = selectMessage(catalogValue(selectedCatalog, key), locale, values);
    const fallback = selectMessage(catalogValue(fallbackCatalog, key), defaultLocale, values);
    return interpolate(selected ?? fallback ?? key, values);
  }, [fallbackCatalog, locale, selectedCatalog]);

  const context = useMemo<I18nContextValue>(() => ({
    locale,
    dir: localeDirection(locale),
    setLocale,
    t,
    number: (value, options) => new Intl.NumberFormat(locale, options).format(value),
    percent: (value, options) => new Intl.NumberFormat(locale, {
      style: 'percent', maximumFractionDigits: 1, ...options,
    }).format(value),
    date: (value, options) => {
      const parsed = validDate(value);
      return parsed ? new Intl.DateTimeFormat(locale, options ?? { dateStyle: 'medium' }).format(parsed) : t('common.notAvailable');
    },
    time: (value, options) => {
      const parsed = validDate(value);
      return parsed ? new Intl.DateTimeFormat(locale, options ?? { timeStyle: 'short' }).format(parsed) : t('common.notAvailable');
    },
    duration: (milliseconds) => {
      const seconds = Math.max(0, Math.round(milliseconds / 1000));
      if (seconds < 60) return t('formats.durationSeconds', { count: seconds, value: new Intl.NumberFormat(locale).format(seconds) });
      const minutes = Math.round(seconds / 60);
      return t('formats.durationMinutes', { count: minutes, value: new Intl.NumberFormat(locale).format(minutes) });
    },
  }), [locale, setLocale, t]);

  return <I18nContext.Provider value={context}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const context = useContext(I18nContext);
  if (!context) throw new Error('useI18n must be used within I18nProvider');
  return context;
}
