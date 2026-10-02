export const pluralCategories = ['zero', 'one', 'two', 'few', 'many', 'other'] as const;

export type PluralCategory = (typeof pluralCategories)[number];
export type PluralMessage = Partial<Record<PluralCategory, string>> & { other: string };
export type CatalogValue = string | PluralMessage | Catalog;
export type Catalog = { [key: string]: CatalogValue };
export type CatalogLoader = () => Promise<Catalog>;
