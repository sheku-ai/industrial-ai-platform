import { ProductIntegrationWorkspace } from '../../components/product/ProductIntegrationWorkspace';
import { PageHeader } from '../../components/layout/PageHeader';

export default function ProductIntegrationPage() {
  return (
    <>
      <PageHeader page="product" />
      <ProductIntegrationWorkspace />
    </>
  );
}
