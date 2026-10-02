import {
  defaultLocale,
  isSupportedLocale,
  localeRegistry,
  localeUsesEnglishFallback,
  resolveLocale,
  type SupportedLocale,
} from './config';
import { pluralCategories, type Catalog } from './types';

export type { Catalog, CatalogValue, PluralCategory, PluralMessage } from './types';

export type LoadedCatalog = {
  catalog: Catalog;
  locale: SupportedLocale;
};

const catalogCache = new Map<SupportedLocale, Catalog>();
const catalogRequests = new Map<SupportedLocale, Promise<Catalog>>();

function isMapping(value: unknown): value is Catalog {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

function isPluralMessage(value: unknown): boolean {
  if (!isMapping(value)) return false;
  const keys = Object.keys(value);
  return keys.length > 0 && keys.every((key) => (pluralCategories as readonly string[]).includes(key));
}

export function composeCatalog(base: Catalog, localized: Catalog): Catalog {
  const effective: Catalog = { ...base };
  for (const [key, localizedValue] of Object.entries(localized)) {
    const baseValue = base[key];
    if (
      isMapping(baseValue)
      && isMapping(localizedValue)
      && !isPluralMessage(baseValue)
      && !isPluralMessage(localizedValue)
    ) {
      effective[key] = composeCatalog(baseValue, localizedValue);
      continue;
    }
    if (isMapping(baseValue) && isMapping(localizedValue) && isPluralMessage(baseValue)) {
      effective[key] = { ...baseValue, ...localizedValue };
      continue;
    }
    effective[key] = localizedValue;
  }
  return effective;
}

export function seedCatalog(locale: SupportedLocale, catalog: Catalog): void {
  catalogCache.set(locale, catalog);
}

async function loadExactCatalog(locale: SupportedLocale): Promise<Catalog> {
  const cached = catalogCache.get(locale);
  if (cached) return cached;

  const existingRequest = catalogRequests.get(locale);
  if (existingRequest) return existingRequest;

  const request: Promise<Catalog> = localeRegistry[locale].loader()
    .then((loaded) => {
      catalogCache.set(locale, loaded);
      return loaded;
    })
    .finally(() => {
      if (catalogRequests.get(locale) === request) catalogRequests.delete(locale);
    });

  catalogRequests.set(locale, request);
  return request;
}

export async function loadCatalog(requestedLocale: unknown): Promise<LoadedCatalog> {
  const locale = isSupportedLocale(requestedLocale) ? resolveLocale([requestedLocale]) : defaultLocale;
  try {
    const localized = await loadExactCatalog(locale);
    if (!localeUsesEnglishFallback(locale)) return { catalog: localized, locale };
    const english = await loadExactCatalog(defaultLocale);
    return { catalog: composeCatalog(english, localized), locale };
  } catch (error) {
    if (locale === defaultLocale) throw error;
    return { catalog: await loadExactCatalog(defaultLocale), locale: defaultLocale };
  }
}
