import { AssistantWorkspace } from '../../components/ai/AssistantWorkspace';
import { PageHeader } from '../../components/layout/PageHeader';

export default function AskAIPage() {
  return (
    <>
      <PageHeader page="ask" />
      <AssistantWorkspace />
    </>
  );
}
