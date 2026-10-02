'use client';

import { useI18n } from '../../i18n/I18nProvider';

import { LocalizedText } from '../layout/LocalizedText';

import { useState } from 'react';

import { platformCapabilityAvailable, type PlatformCapabilityKey } from '../../lib/platform-dashboard-api';
import { useOrganization } from './OrganizationContext';
import { AdministrationWorkspace } from './AdministrationWorkspace';

const destinations: {
  titleKey: string;
  descriptionKey: string;
  href: string;
  platformCapability?: PlatformCapabilityKey;
}[] = [
  { titleKey: 'dynamic.organizationProfile', descriptionKey: 'dynamic.organizationProfileHelp', href: '#organization-overview' },
  { titleKey: 'copy.structure_9482c5d5', descriptionKey: 'dynamic.organizationStructureHelp', href: '/organization/structure' },
  { titleKey: 'pages.security.title', descriptionKey: 'dynamic.securityAdministrationHelp', href: '/security' },
  { titleKey: 'copy.document_configuration_2592490b', descriptionKey: 'dynamic.documentConfigurationHelp', href: '/organization/document-configuration' },
  { titleKey: 'dynamic.knowledgeConfiguration', descriptionKey: 'dynamic.knowledgeConfigurationHelp', href: '/knowledge' },
  { titleKey: 'dynamic.aiConfiguration', descriptionKey: 'dynamic.aiConfigurationHelp', href: '/ai' },
  { titleKey: 'dynamic.platformCapabilities', descriptionKey: 'dynamic.platformCapabilitiesHelp', href: '/production', platformCapability: 'release_readiness' },
];

export function AdministrationHub() {
  const { t } = useI18n();
  const { capabilitiesLoading, capabilitiesResolved, navigationCapabilities } = useOrganization();
  const [overviewOpen, setOverviewOpen] = useState(false);
  return (
    <div className="product-workspace">
      <section className="administration-grid" aria-label={t('copy.administration_destinations_73efadf9')}>
        {destinations.map((destination) => {
          const restricted = Boolean(destination.platformCapability && (
            !capabilitiesResolved
            || capabilitiesLoading
            || !platformCapabilityAvailable(navigationCapabilities, destination.platformCapability)
          ));
          return restricted ? (
            <span aria-disabled="true" className="administration-destination is-disabled" key={destination.titleKey} title={capabilitiesResolved && !capabilitiesLoading ? t('navigation.platformPermissionRequired') : t('copy.dynamic_accessevaluating_88721262')}><span>{t(destination.titleKey)}</span><p>{capabilitiesResolved && !capabilitiesLoading ? t('navigation.platformPermissionRequired') : t('copy.checking_access_c5108c02')}</p></span>
          ) : (
            <a className="administration-destination" href={destination.href} key={destination.titleKey} onClick={() => { if (destination.href.startsWith('#')) setOverviewOpen(true); }}><span>{t(destination.titleKey)}</span><p>{t(destination.descriptionKey)}</p><small><LocalizedText id="copy.open_6f4789b0" /></small></a>
          );
        })}
      </section>
      <details className="advanced-panel" id="organization-overview" onToggle={(event) => setOverviewOpen(event.currentTarget.open)} open={overviewOpen}>
        <summary><LocalizedText id="copy.organization_profile_and_platform_overview_3ee16c7a" /></summary>
        <div className="advanced-panel-content">{overviewOpen ? <AdministrationWorkspace /> : null}</div>
      </details>
    </div>
  );
}
