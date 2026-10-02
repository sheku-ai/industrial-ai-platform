import { ModelProviderCenterWorkspace } from '../../components/models/ModelProviderCenterWorkspace';
import { PageHeader } from '../../components/layout/PageHeader';

export default function ModelProviderCenterPage() {
  return (
    <>
      <PageHeader page="models" />
      <ModelProviderCenterWorkspace />
    </>
  );
}
