'use client';

import { PlatformCapabilityState } from '../layout/PlatformCapabilityState';
import { useOrganization } from '../organization/OrganizationContext';
import { SchedulerBackgroundServicesCenter } from './SchedulerBackgroundServicesCenter';
import { SchedulerWorkspace } from './SchedulerWorkspace';

export function SchedulerSurface() {
  const { organization } = useOrganization();
  return (
    <PlatformCapabilityState capability="scheduler">
      {(actionAvailable) => (
        <>
          <SchedulerBackgroundServicesCenter />
          {organization ? <SchedulerWorkspace canAdminister={actionAvailable} /> : null}
        </>
      )}
    </PlatformCapabilityState>
  );
}
