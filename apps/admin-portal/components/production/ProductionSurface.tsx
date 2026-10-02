'use client';

import { PlatformCapabilityState } from '../layout/PlatformCapabilityState';
import { ProductionReadinessCenter } from './ProductionReadinessCenter';

export function ProductionSurface() {
  return (
    <PlatformCapabilityState capability="release_readiness">
      {(actionAvailable) => <ProductionReadinessCenter canAdminister={actionAvailable} />}
    </PlatformCapabilityState>
  );
}
