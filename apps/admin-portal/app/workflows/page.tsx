import { WorkflowStudioWorkspace } from '../../components/workflows/WorkflowStudioWorkspace';
import { PageHeader } from '../../components/layout/PageHeader';

export default function WorkflowStudioPage() {
  return (
    <>
      <PageHeader page="workflows" />
      <WorkflowStudioWorkspace />
    </>
  );
}
