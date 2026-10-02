'use client';

import { localeRegistry, supportedLocales, type SupportedLocale } from '../../i18n/config';
import { useI18n } from '../../i18n/I18nProvider';

export function LanguageSelector() {
  const { locale, setLocale, t } = useI18n();
  return (
    <label className="language-selector" htmlFor="global-language-selector">
      <span aria-hidden="true" className="language-selector-icon">◎</span>
      <span className="sr-only">{t('language.selectorLabel')}</span>
      <select
        aria-label={t('language.selectorLabel')}
        id="global-language-selector"
        value={locale}
        onChange={(event) => setLocale(event.target.value as SupportedLocale)}
      >
        {supportedLocales.map((candidate) => (
          <option key={candidate} lang={candidate} value={candidate}>
            {localeRegistry[candidate].name}
            {localeRegistry[candidate].status === 'preview' ? ` — ${t('language.preview')}` : ''}
          </option>
        ))}
      </select>
    </label>
  );
}
