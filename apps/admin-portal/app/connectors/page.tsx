import { ConnectorWorkspace } from '../../components/connectors/ConnectorWorkspace';
import { PageHeader } from '../../components/layout/PageHeader';

export default function ConnectorsPage() {
  return (
    <>
      <PageHeader page="connectors" />
      <ConnectorWorkspace />
    </>
  );
}
