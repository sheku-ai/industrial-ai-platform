'use client';

import { useI18n } from '../../i18n/I18nProvider';

type PageKey = 'ai' | 'analytics' | 'ask' | 'connectors' | 'documents' | 'governance' | 'integrations' |
  'knowledge' | 'models' | 'operations' | 'organization' | 'product' | 'production' | 'runtime' |
  'scheduler' | 'search' | 'security' | 'workflows';

export function PageHeader({ page }: { page: PageKey }) {
  const { t } = useI18n();
  const section = t(`pages.${page}.section`);
  const hasSection = section !== `pages.${page}.section`;
  return (
    <header className="header">
      {hasSection ? <span className="eyebrow">{section}</span> : null}
      <h1>{t(`pages.${page}.title`)}</h1>
      <p>{t(`pages.${page}.description`)}</p>
    </header>
  );
}
