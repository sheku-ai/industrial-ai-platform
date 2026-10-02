import { GovernanceCenter } from '../../components/governance/GovernanceCenter';
import { PageHeader } from '../../components/layout/PageHeader';

export default function GovernancePage() {
  return (
    <>
      <PageHeader page="governance" />
      <GovernanceCenter />
    </>
  );
}
