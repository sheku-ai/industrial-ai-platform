import { SecurityCenterWorkspace } from '../../components/security/SecurityCenterWorkspace';
import { PageHeader } from '../../components/layout/PageHeader';

export default function SecurityCenterPage() {
  return (
    <>
      <PageHeader page="security" />
      <SecurityCenterWorkspace />
    </>
  );
}
