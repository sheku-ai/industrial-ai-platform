
import { LocalizedText } from '../../components/layout/LocalizedText';
import { AIConfigurationDestination } from '../../components/ai/AIConfigurationDestination';
import { AIStudioWorkspace } from '../../components/ai/AIStudioWorkspace';
import { LegacyAIWorkspaceRedirect } from '../../components/ai/LegacyAIWorkspaceRedirect';
import { PageHeader } from '../../components/layout/PageHeader';

export default function AIPage() {
  return (
    <>
      <LegacyAIWorkspaceRedirect />
      <PageHeader page="ai" />
      <section className="administration-grid"><AIConfigurationDestination /><a className="administration-destination" href="/ask"><span><LocalizedText id="pages.ask.title" /></span><p><LocalizedText id="copy.open_the_daily_conversation_experience_4d349b08" /></p><small><LocalizedText id="copy.open_6f4789b0" /></small></a></section>
      <section className="capability-section" id="ai-studio">
        <AIStudioWorkspace />
      </section>
    </>
  );
}
