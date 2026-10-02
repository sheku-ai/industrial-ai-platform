
import { ConnectorWorkspace } from '../../components/connectors/ConnectorWorkspace';
import { PageHeader } from '../../components/layout/PageHeader';

export default function EnterpriseApiIntegrationPage() {
  return (
    <>
      <PageHeader page="integrations" />
      <ConnectorWorkspace />
    </>
  );
}
