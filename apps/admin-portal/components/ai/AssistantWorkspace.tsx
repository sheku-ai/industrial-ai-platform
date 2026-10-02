'use client';

import { LocalizedDate, LocalizedText } from '../layout/LocalizedText';
import { useI18n } from '../../i18n/I18nProvider';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  getAssistantWorkspaceCapabilities,
  getAssistantWorkspaceRuntime,
  type AssistantWorkspaceCapabilities,
  type AssistantWorkspaceRuntime,
} from '../../lib/assistant-workspace-api';
import { PlatformApiError } from '../../lib/platform-api';
import {
  issueMessage,
  localizedApiError,
  localizedAssistantAvailability,
  localizedStatusLabel,
  productStatus,
} from '../../lib/presentation';
import { useOrganization } from '../organization/OrganizationContext';
import { ConversationChatWorkspace } from './ConversationChatWorkspace';

export function AssistantWorkspace() {
  const { t } = useI18n();
  const { organization } = useOrganization();
  const [runtime, setRuntime] = useState<AssistantWorkspaceRuntime | null>(null);
  const [capabilities, setCapabilities] = useState<AssistantWorkspaceCapabilities | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  const requestVersion = useRef(0);

  const load = useCallback(async () => {
    if (!organization) return;
    const version = ++requestVersion.current;
    setLoading(true);
    setError(null);
    setErrorStatus(null);
    try {
      const resolved = await getAssistantWorkspaceCapabilities(organization.id);
      if (version !== requestVersion.current) return;
      setCapabilities(resolved);
      const payload = resolved.workspace_available ? await getAssistantWorkspaceRuntime(organization.id) : null;
      if (version === requestVersion.current) setRuntime(payload);
    } catch (cause) {
      if (version === requestVersion.current) {
        setErrorStatus(cause instanceof PlatformApiError ? cause.status : null);
        setError(localizedApiError(cause, t, 'feedback.askAiLoadFailed'));
      }
    } finally {
      if (version === requestVersion.current) setLoading(false);
    }
  }, [organization, t]);

  useEffect(() => {
    setRuntime(null);
    setCapabilities(null);
    void load();
    return () => { requestVersion.current += 1; };
  }, [load]);

  const diagnostics = useMemo(() => runtime ? [
    ...(runtime.diagnostics.blocking_issues ?? []),
    ...(runtime.diagnostics.warnings ?? []),
    ...(runtime.diagnostics.pending_capabilities ?? []),
  ] : [], [runtime]);

  if (loading && !runtime) return <section className="card workspace-state"><h2><LocalizedText id="copy.loading_ask_ai_5ed25ce2" /></h2><p><LocalizedText id="copy.retrieving_authorized_assistants_and_conversation_hi_361be7cc" /></p></section>;
  if (errorStatus === 403 || (capabilities && !capabilities.workspace_available)) return <section className="card workspace-state"><span className="eyebrow"><LocalizedText id="copy.access_required_3d2f1a2e" /></span><h2><LocalizedText id="copy.ask_ai_is_unavailable_for_your_account_95345092" /></h2><p>{errorStatus === 403 ? t('errors.forbidden') : <LocalizedText id="copy.an_organization_administrator_must_grant_explicit_as_229e51a5" />}</p><a className="button secondary" href="/security"><LocalizedText id="copy.open_users_access_471c8985" /></a></section>;
  if (!runtime) return <section className="card workspace-state"><h2><LocalizedText id="copy.ask_ai_unavailable_3dcbfb87" /></h2><p>{error ?? <LocalizedText id="copy.the_assistant_workspace_did_not_return_a_persisted_s_9b5ab270" />}</p><button className="button secondary" onClick={() => void load()} type="button"><LocalizedText id="common.actions.retry" /></button></section>;

  const assistants = runtime.assistant_definitions;
  const conversations = runtime.conversations;

  return (
    <div className="product-workspace" data-assistant-workspace="ready">
      {error ? <p className="context-message context-error" role="alert">{t('dynamic.latestAssistantWorkspaceError')} <button className="button secondary" onClick={() => void load()} type="button"><LocalizedText id="common.actions.retry" /></button></p> : null}
      {loading ? <p className="context-message" role="status"><LocalizedText id="copy.refreshing_assistants_and_conversation_history_8f561c42" /></p> : null}
      {capabilities?.chat_available ? (
        <ConversationChatWorkspace assistants={assistants} conversations={conversations} />
      ) : (
        <section className="card inline-state"><div><h2><LocalizedText id="copy.conversation_access_is_not_configured_6107cde0" /></h2><p><LocalizedText id="copy.you_can_view_authorized_assistants_and_history_but_s_4d1f709e" /></p></div><a className="button secondary" href="/security"><LocalizedText id="copy.review_access_0d73310f" /></a></section>
      )}

      <section className="table-card" id="conversation-history">
        <div className="section-header table-heading"><div><span className="eyebrow"><LocalizedText id="copy.persisted_history_8fd87fbc" /></span><h2><LocalizedText id="copy.conversation_history_a03d887e" /></h2><p><LocalizedText id="copy.only_conversations_authorized_for_the_active_organiz_ab69294c" /></p></div><button className="button secondary" onClick={() => void load()} type="button"><LocalizedText id="common.actions.refresh" /></button></div>
        {conversations.length === 0 ? <div className="empty-state"><strong><LocalizedText id="copy.no_conversations_yet_f58811ba" /></strong><p><LocalizedText id="copy.ask_your_first_question_to_create_a_persisted_conver_12377eb2" /></p></div> : (
          <div className="conversation-history-list">{conversations.map((conversation) => <a href={`/ask?conversation=${conversation.conversation_id}`} key={conversation.conversation_id}><span><strong>{conversation.title ?? t('dynamic.newConversation')}</strong><small>{<LocalizedDate value={conversation.last_activity_at} />}</small></span><span>{t('dynamic.turnCount', { count: conversation.turn_count, value: conversation.turn_count })}</span><span className={`product-status product-status-${productStatus(conversation.status)}`}>{localizedStatusLabel(conversation.status, t)}</span></a>)}</div>
        )}
      </section>

      <details className="advanced-panel">
        <summary><LocalizedText id="copy.assistant_status_and_advanced_details_bd46922d" /></summary>
        <div className="advanced-panel-content">
          <section className="table-card"><h2><LocalizedText id="copy.authorized_assistants_bdd82382" /></h2>{assistants.length === 0 ? <p className="muted-text"><LocalizedText id="copy.no_assistant_definitions_are_available_for_this_orga_19878534" /></p> : <table><thead><tr><th><LocalizedText id="ask.assistant" /></th><th><LocalizedText id="common.description" /></th><th><LocalizedText id="copy.availability_681b5b5a" /></th><th><LocalizedText id="copy.assigned_sources_c3dca422" /></th><th><LocalizedText id="copy.searchable_organization_sources_1bdcff63" /></th></tr></thead><tbody>{assistants.map((assistant) => <tr key={assistant.assistant_id}><td>{assistant.assistant_name}</td><td>{assistant.description ?? <LocalizedText id="copy.no_description_provided_fe3f10ae" />}</td><td>{localizedAssistantAvailability(assistant.availability, assistant.assistant_status, t).title}</td><td>{String(assistant.availability.assigned_knowledge_source_count ?? 0)}</td><td>{String(assistant.availability.searchable_organization_source_count ?? 0)}</td></tr>)}</tbody></table>}</section>
          <section className="table-card"><h2><LocalizedText id="copy.diagnostics_3af2279f" /></h2>{diagnostics.length === 0 ? <p className="muted-text"><LocalizedText id="copy.no_diagnostic_items_reported_2e3c0092" /></p> : <ul className="compact-list">{diagnostics.map((item, index) => <li key={index}>{issueMessage(item, t('dynamic.detailsAvailable'))}</li>)}</ul>}</section>
        </div>
      </details>
    </div>
  );
}
