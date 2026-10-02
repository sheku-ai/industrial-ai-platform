import { KnowledgeWorkspace } from '../../components/knowledge/KnowledgeWorkspace';
import { PageHeader } from '../../components/layout/PageHeader';

export default function KnowledgePage() {
  return (
    <>
      <PageHeader page="knowledge" />
      <KnowledgeWorkspace />
    </>
  );
}
