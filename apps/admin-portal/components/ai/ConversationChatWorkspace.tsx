'use client';

import { LocalizedText } from '../layout/LocalizedText';

import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';

import { useI18n } from '../../i18n/I18nProvider';
import type { AssistantConversationItem, AssistantDefinitionItem } from '../../lib/assistant-workspace-api';
import { organizationHeaders, platformApi, type JsonObject } from '../../lib/platform-api';
import {
  localizedApiError,
  localizedAssistantAvailability,
  localizedStatusLabel,
} from '../../lib/presentation';
import { useOrganization } from '../organization/OrganizationContext';

type ChatTurn = JsonObject & {
  conversation_turn_id?: string;
  turn_index?: number;
  turn_role?: string;
  turn_status?: string;
  input_text?: string | null;
  output_text?: string | null;
  ordered_citations?: JsonObject[];
  turn_metadata?: JsonObject;
};

type ChatRuntime = JsonObject & {
  conversation_id?: string;
  conversation_turns?: ChatTurn[];
  blocking_issues?: JsonObject[];
};

type Translate = (key: string, values?: Record<string, string | number | boolean>) => string;

function issueMessage(issue: JsonObject, t: Translate): string {
  const code = String(issue.code ?? '');
  if (code === 'message_empty') return t('ask.errors.emptyMessage');
  if (code.includes('not_authorized') || code.includes('forbidden')) return t('errors.forbidden');
  return t('ask.errors.conversationStopped');
}

function turnText(turn: ChatTurn, t: Translate): string {
  if (turn.turn_metadata?.no_evidence_response === true) return t('ask.noEvidence');
  return String(turn.output_text ?? turn.input_text ?? '');
}

function citationTitle(citation: JsonObject, index: number, t: Translate): string {
  return String(
    citation.document_title
      ?? citation.original_filename
      ?? citation.title
      ?? citation.label
      ?? t('ask.sourceTitle', { number: index + 1 }),
  );
}

function citationHref(citation: JsonObject): string | null {
  if (typeof citation.document_href === 'string' && citation.document_href) return citation.document_href;
  if (typeof citation.document_record_id === 'string' && citation.document_record_id) {
    return `/documents#document-${citation.document_record_id}`;
  }
  return null;
}

export function ConversationChatWorkspace({
  assistants,
  conversations,
}: {
  assistants: AssistantDefinitionItem[];
  conversations: AssistantConversationItem[];
}) {
  const { organization } = useOrganization();
  const { locale, t } = useI18n();
  const [assistantId, setAssistantId] = useState(assistants[0]?.assistant_id ?? '');
  const [conversationId, setConversationId] = useState('');
  const [runtime, setRuntime] = useState<ChatRuntime | null>(null);
  const [message, setMessage] = useState('');
  const [loadingConversation, setLoadingConversation] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const initialConversationHandled = useRef(false);
  const pendingRequest = useRef<{ message: string; requestId: string } | null>(null);
  const sendInFlight = useRef(false);

  useEffect(() => {
    if (!assistantId && assistants[0]?.assistant_id) setAssistantId(assistants[0].assistant_id);
  }, [assistantId, assistants]);

  const availableConversations = useMemo(
    () => conversations.filter((conversation) => !assistantId || conversation.assistant_id === assistantId),
    [assistantId, conversations],
  );

  useEffect(() => {
    if (initialConversationHandled.current || conversations.length === 0) return;
    initialConversationHandled.current = true;
    const requested = new URLSearchParams(window.location.search).get('conversation');
    if (requested && conversations.some((conversation) => conversation.conversation_id === requested)) {
      void selectConversation(requested);
    }
  // Conversation deep links are resolved once to avoid duplicate reads during rerenders.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversations]);

  async function selectConversation(nextConversationId: string) {
    setConversationId(nextConversationId);
    setRuntime(null);
    setError(null);
    if (!nextConversationId) return;

    setLoadingConversation(true);
    try {
      if (!organization) throw new Error(t('ask.errors.selectOrganization'));
      setRuntime(await platformApi.get<ChatRuntime>(
        `/api/assistants/chat/${nextConversationId}`,
        organizationHeaders(organization.id),
      ));
    } catch (cause) {
      setError(localizedApiError(cause, t, 'ask.errors.historyUnavailable'));
    } finally {
      setLoadingConversation(false);
    }
  }

  async function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const preparedMessage = message.trim();
    if (!assistantId || !organization || !preparedMessage || !availability?.runtimeAvailable || sendInFlight.current) return;

    sendInFlight.current = true;
    setSending(true);
    setError(null);
    const requestId = pendingRequest.current?.message === preparedMessage
      ? pendingRequest.current.requestId
      : crypto.randomUUID();
    pendingRequest.current = { message: preparedMessage, requestId };
    try {
      const payload = await platformApi.post<ChatRuntime>(
        '/api/assistants/chat',
        {
          assistant_id: assistantId,
          conversation_id: conversationId || null,
          request_id: requestId,
          message: preparedMessage,
          requested_by: 'admin-portal',
          runtime_context: { interaction_surface: 'admin_portal', locale },
          runtime_metadata: { interaction_surface: 'admin_portal', locale },
        },
        organizationHeaders(organization.id),
        60_000,
      );
      const persistedConversationId = String(payload.conversation_id ?? conversationId);
      setConversationId(persistedConversationId);
      setRuntime(await platformApi.get<ChatRuntime>(
        `/api/assistants/chat/${persistedConversationId}`,
        organizationHeaders(organization.id),
      ));
      setMessage('');
      pendingRequest.current = null;
    } catch (cause) {
      setError(localizedApiError(cause, t, 'ask.errors.messageFailed'));
    } finally {
      sendInFlight.current = false;
      setSending(false);
    }
  }

  const turns = Array.isArray(runtime?.conversation_turns) ? runtime.conversation_turns : [];
  const blockingIssues = Array.isArray(runtime?.blocking_issues) ? runtime.blocking_issues : [];
  const selectedAssistant = assistants.find((assistant) => assistant.assistant_id === assistantId);
  const searchableSourceCount = Number(selectedAssistant?.availability.searchable_organization_source_count ?? 0);
  const assignedSourceCount = Number(selectedAssistant?.availability.assigned_knowledge_source_count ?? 0);
  const availability = selectedAssistant
    ? localizedAssistantAvailability(selectedAssistant.availability, selectedAssistant.assistant_status, t)
    : null;
  const composerDisabled = sending || !assistantId || !organization || !availability?.runtimeAvailable;

  return (
    <section className="table-card chat-workspace" data-assistant-workspace-section="chat" id="chat">
      <div className="section-header chat-header">
        <span className="eyebrow"><LocalizedText id="copy.ask_using_organization_knowledge_b7622281" /></span>
        <h2>{t('ask.conversation')}</h2>
        <p>{t('ask.conversationHelp')}</p>
      </div>
      <div className="chat-layout">
        <aside className="chat-controls" aria-label={t('copy.conversation_settings_575f3f99')}>
          <label className="field-label" htmlFor="chat-assistant">{t('ask.assistant')}</label>
          <select aria-describedby="chat-assistant-help" className="field-control" disabled={sending || assistants.length === 0} id="chat-assistant" onChange={(event) => { setAssistantId(event.target.value); void selectConversation(''); }} value={assistantId}>
            {assistants.length === 0 ? <option value="">{t('ask.noAssistants')}</option> : null}
            {assistants.map((assistant) => <option key={assistant.assistant_id} value={assistant.assistant_id}>{assistant.assistant_name}</option>)}
          </select>
          <p className="muted-text" id="chat-assistant-help">{t('ask.assistantHelp')}</p>
          <label className="field-label" htmlFor="chat-conversation">{t('ask.conversationLabel')}</label>
          <select className="field-control" disabled={sending || loadingConversation} id="chat-conversation" onChange={(event) => void selectConversation(event.target.value)} value={conversationId}>
            <option value="">{t('ask.newConversation')}</option>
            {availableConversations.map((conversation) => (
              <option key={conversation.conversation_id} value={conversation.conversation_id}>{conversation.title ?? t('ask.conversationTurns', { count: conversation.turn_count })}</option>
            ))}
          </select>
          <p className="muted-text">{t('ask.organization', { name: organization?.name ?? t('common.notSelected') })}</p>
          <div className="assistant-availability" id="chat-availability" role="status">
            <strong>{availability?.title ?? t('ask.selectAssistant')}</strong>
            {availability ? (
              <details className="assistant-availability-details">
                <summary>{t('common.advancedDetails')}</summary>
                <p>{availability.description}</p>
              </details>
            ) : <p>{t('ask.sourceAvailabilityPending')}</p>}
          </div>
          <p className="muted-text">{selectedAssistant ? t('ask.sourcesAvailable', { count: searchableSourceCount }) : t('ask.sourceAvailabilityPending')}</p>
          <details className="inline-help"><summary>{t('ask.howProduced')}</summary><p>{t('ask.searchCondition')}</p>{selectedAssistant ? <p>{t('ask.assignedSources', { count: assignedSourceCount })}</p> : null}</details>
        </aside>
        <div className="chat-panel">
          <div aria-live="polite" className="chat-transcript">
            {loadingConversation ? <p className="muted-text">{t('ask.loadingConversation')}</p> : null}
            {!loadingConversation && turns.length === 0 ? (
              <div className="empty-state"><strong>{t('ask.noMessages')}</strong><p>{t('ask.noMessagesHelp')}</p></div>
            ) : null}
            {turns.map((turn, index) => (
              <article className={`chat-message chat-message-${turn.turn_role ?? 'system'}`} key={turn.conversation_turn_id ?? `${turn.turn_index}-${index}`}>
                <div className="chat-message-meta"><strong>{turn.turn_role === 'assistant' ? t('ask.assistant') : turn.turn_role === 'user' ? t('ask.you') : t('dynamic.systemRole')}</strong><span>{localizedStatusLabel(turn.turn_status ?? 'recorded', t)}</span></div>
                {turnText(turn, t) ? <p className="chat-message-body">{turnText(turn, t)}</p> : null}
                {Array.isArray(turn.ordered_citations) && turn.ordered_citations.length > 0 ? <div className="chat-citations"><strong>{t('ask.sources')}</strong>{turn.ordered_citations.map((citation, citationIndex) => {
                  const href = citationHref(citation);
                  const title = citationTitle(citation, citationIndex, t);
                  return href ? <a href={href} key={citationIndex}>{title}</a> : <span key={citationIndex}>{title}</span>;
                })}</div> : null}
              </article>
            ))}
          </div>
          {error ? <p className="context-message context-error" role="alert">{error}</p> : null}
          {blockingIssues.length > 0 ? <div className="context-message context-error" role="alert">{blockingIssues.map((issue, index) => <p key={`${issue.code ?? 'issue'}-${index}`}>{issueMessage(issue, t)}</p>)}</div> : null}
          <form className="chat-composer" onSubmit={sendMessage}>
            <label className="field-label" htmlFor="chat-message">{t('ask.message')}</label>
            <textarea aria-describedby="chat-message-help chat-availability" className="field-control" disabled={composerDisabled} id="chat-message" onChange={(event) => setMessage(event.target.value)} placeholder={t('ask.messagePlaceholder')} rows={3} value={message} />
            <small className="muted-text" id="chat-message-help">{t(availability?.runtimeAvailable ? 'ask.messageHelp' : 'ask.messageUnavailableHelp')}</small>
            <button className="button" disabled={composerDisabled || !message.trim()} type="submit">{t(sending ? 'ask.processing' : conversationId ? 'ask.continueConversation' : 'ask.startConversation')}</button>
          </form>
        </div>
      </div>
    </section>
  );
}
