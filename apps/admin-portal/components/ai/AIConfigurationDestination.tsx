'use client';

import { LocalizedText } from '../layout/LocalizedText';
import { useOrganization } from '../organization/OrganizationContext';

export function AIConfigurationDestination() {
  const {
    capabilitiesLoading,
    capabilitiesResolved,
    navigationCapabilities,
  } = useOrganization();
  const accessResolved = capabilitiesResolved && !capabilitiesLoading;
  const canReadConfiguration = Boolean(navigationCapabilities?.ai_configuration?.visible);

  if (!accessResolved || !canReadConfiguration) {
    return (
      <div aria-disabled="true" className="administration-destination is-disabled">
        <span><LocalizedText id="copy.models_providers_7736355d" /></span>
        <p><LocalizedText id="copy.review_governed_model_and_provider_configuration_4bebbffd" /></p>
        <small>
          <LocalizedText
            id={accessResolved
              ? 'copy.access_required_3d2f1a2e'
              : 'copy.checking_access_c5108c02'}
          />
        </small>
      </div>
    );
  }

  return (
    <a className="administration-destination" href="/models">
      <span><LocalizedText id="copy.models_providers_7736355d" /></span>
      <p><LocalizedText id="copy.review_governed_model_and_provider_configuration_4bebbffd" /></p>
      <small><LocalizedText id="copy.open_6f4789b0" /></small>
    </a>
  );
}
