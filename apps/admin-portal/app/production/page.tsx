import { ProductionSurface } from '../../components/production/ProductionSurface';
import { PageHeader } from '../../components/layout/PageHeader';

export default function ProductionReadinessPage() {
  return (
    <>
      <PageHeader page="production" />
      <ProductionSurface />
    </>
  );
}
