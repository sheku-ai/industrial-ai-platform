
import { Suspense } from 'react';

import { OperationsSurface } from '../../components/operations/OperationsSurface';
import { PageHeader } from '../../components/layout/PageHeader';

export default function OperationsPage() {
  return (
    <>
      <PageHeader page="operations" />
      <Suspense fallback={null}>
        <OperationsSurface />
      </Suspense>
    </>
  );
}
