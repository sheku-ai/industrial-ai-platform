import { AdministrationHub } from '../../components/organization/AdministrationHub';
import { PageHeader } from '../../components/layout/PageHeader';

export default function OrganizationPage() {
  return (
    <>
      <PageHeader page="organization" />
      <AdministrationHub />
    </>
  );
}
