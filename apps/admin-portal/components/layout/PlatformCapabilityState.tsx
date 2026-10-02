'use client';

import type { ReactNode } from 'react';

import { useI18n } from '../../i18n/I18nProvider';
import type { PlatformCapabilityKey } from '../../lib/platform-dashboard-api';
import { LocalizedText } from './LocalizedText';
import { useOrganization } from '../organization/OrganizationContext';

type PlatformCapabilityStateProps = {
  capability: PlatformCapabilityKey;
  children: (actionAvailable: boolean) => ReactNode;
};

export function PlatformCapabilityState({
  capability,
  children,
}: PlatformCapabilityStateProps) {
  const { t } = useI18n();
  const {
    capabilitiesError,
    capabilitiesLoading,
    capabilitiesResolved,
    navigationCapabilities,
    refreshCapabilities,
  } = useOrganization();
  const resolved = navigationCapabilities?.platform[capability];

  if (capabilitiesError && !capabilitiesResolved) {
    return (
      <section className="card workspace-state" role="alert">
        <h2><LocalizedText id="copy.access_could_not_be_evaluated_d4d8e1b3" /></h2>
        <p>{capabilitiesError}</p>
        <button className="button secondary" onClick={() => void refreshCapabilities()} type="button">
          <LocalizedText id="common.actions.retry" />
        </button>
      </section>
    );
  }

  if (capabilitiesLoading || !capabilitiesResolved) {
    return (
      <section className="card workspace-state" role="status">
        <h2><LocalizedText id="copy.checking_access_c5108c02" /></h2>
      </section>
    );
  }

  if (!resolved?.visible) {
    return (
      <section className="card workspace-state" data-platform-capability={capability} data-platform-capability-state="restricted">
        <span className="eyebrow"><LocalizedText id="copy.access_required_3d2f1a2e" /></span>
        <h2>{t('navigation.platformPermissionRequired')}</h2>
        <p>{t('navigation.platformPermissionRequired')}</p>
      </section>
    );
  }

  return children(resolved.action_available);
}
