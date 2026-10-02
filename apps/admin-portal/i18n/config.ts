import type { Catalog, CatalogLoader } from './types';

export type LocaleDirection = 'ltr' | 'rtl';
export type LocaleStatus = 'available' | 'preview';
export type LocaleDefinition = {
  code: string;
  name: string;
  direction: LocaleDirection;
  status: LocaleStatus;
  loader: CatalogLoader;
};

function catalog(loader: () => Promise<{ default: Catalog }>): CatalogLoader {
  return async () => (await loader()).default;
}

export const localeRegistry = {
  en: { code: 'en', name: 'English', direction: 'ltr', status: 'available', loader: catalog(() => import('./en.json')) },
  'zh-CN': { code: 'zh-CN', name: '中文', direction: 'ltr', status: 'preview', loader: catalog(() => import('./zh-CN.json')) },
  hi: { code: 'hi', name: 'हिन्दी', direction: 'ltr', status: 'preview', loader: catalog(() => import('./hi.json')) },
  es: { code: 'es', name: 'Español', direction: 'ltr', status: 'available', loader: catalog(() => import('./es.json')) },
  ar: { code: 'ar', name: 'العربية', direction: 'rtl', status: 'preview', loader: catalog(() => import('./ar.json')) },
  fr: { code: 'fr', name: 'Français', direction: 'ltr', status: 'preview', loader: catalog(() => import('./fr.json')) },
  bn: { code: 'bn', name: 'বাংলা', direction: 'ltr', status: 'preview', loader: catalog(() => import('./bn.json')) },
  pt: { code: 'pt', name: 'Português', direction: 'ltr', status: 'preview', loader: catalog(() => import('./pt.json')) },
  ru: { code: 'ru', name: 'Русский', direction: 'ltr', status: 'preview', loader: catalog(() => import('./ru.json')) },
  ur: { code: 'ur', name: 'اردو', direction: 'rtl', status: 'preview', loader: catalog(() => import('./ur.json')) },
  ja: { code: 'ja', name: '日本語', direction: 'ltr', status: 'preview', loader: catalog(() => import('./ja.json')) },
  de: { code: 'de', name: 'Deutsch', direction: 'ltr', status: 'preview', loader: catalog(() => import('./de.json')) },
  ko: { code: 'ko', name: '한국어', direction: 'ltr', status: 'preview', loader: catalog(() => import('./ko.json')) },
  it: { code: 'it', name: 'Italiano', direction: 'ltr', status: 'preview', loader: catalog(() => import('./it.json')) },
  nl: { code: 'nl', name: 'Nederlands', direction: 'ltr', status: 'preview', loader: catalog(() => import('./nl.json')) },
  pl: { code: 'pl', name: 'Polski', direction: 'ltr', status: 'preview', loader: catalog(() => import('./pl.json')) },
  tr: { code: 'tr', name: 'Türkçe', direction: 'ltr', status: 'preview', loader: catalog(() => import('./tr.json')) },
  id: { code: 'id', name: 'Bahasa Indonesia', direction: 'ltr', status: 'preview', loader: catalog(() => import('./id.json')) },
  th: { code: 'th', name: 'ไทย', direction: 'ltr', status: 'preview', loader: catalog(() => import('./th.json')) },
  vi: { code: 'vi', name: 'Tiếng Việt', direction: 'ltr', status: 'preview', loader: catalog(() => import('./vi.json')) },
} as const satisfies Record<string, LocaleDefinition>;

export type SupportedLocale = keyof typeof localeRegistry;

export const supportedLocales = Object.freeze(Object.keys(localeRegistry) as SupportedLocale[]);
export const defaultLocale: SupportedLocale = 'en';
export const localeStorageKey = 'industrial-ai-platform.locale.v1';
export const localeCookieKey = 'industrial-ai-platform.locale';
export const localeCookieMaxAge = 60 * 60 * 24 * 365;

export const localeNames = Object.fromEntries(
  supportedLocales.map((locale) => [locale, localeRegistry[locale].name]),
) as Record<SupportedLocale, string>;

const normalizedLocales = new Map<string, SupportedLocale>(
  supportedLocales.map((locale) => [locale.toLowerCase(), locale]),
);

export function isSupportedLocale(value: unknown): value is SupportedLocale {
  return typeof value === 'string' && Object.hasOwn(localeRegistry, value);
}

export function resolveLocale(candidates: readonly unknown[]): SupportedLocale {
  for (const candidate of candidates) {
    if (typeof candidate !== 'string' || !candidate.trim()) continue;
    const normalized = candidate.trim().replaceAll('_', '-').toLowerCase();
    const exact = normalizedLocales.get(normalized);
    if (exact) return exact;
    const base = normalized.split('-')[0];
    const baseMatch = normalizedLocales.get(base);
    if (baseMatch) return baseMatch;
  }
  return defaultLocale;
}

export function localeDirection(locale: SupportedLocale): 'ltr' | 'rtl' {
  return localeRegistry[locale].direction;
}

export function localeUsesEnglishFallback(locale: SupportedLocale): boolean {
  return localeRegistry[locale].status === 'preview';
}
