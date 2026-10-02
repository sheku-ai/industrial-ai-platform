'use client';

import { LocalizedDate, LocalizedText } from '../layout/LocalizedText';

import { useI18n } from '../../i18n/I18nProvider';

import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';

import { getAssistantWorkspaceRuntime, type AssistantConversationItem } from '../../lib/assistant-workspace-api';
import { getDocumentWorkspaceRuntime, type DocumentRegistryItem } from '../../lib/document-workspace-api';
import { getGovernanceCenterRuntime, type GovernanceCenterRuntime } from '../../lib/governance-center-api';
import { installationSetupApi, type InstallationStatus } from '../../lib/installation-setup-api';
import { normalizeGovernanceDiagnostics } from '../../lib/governance-presentation';
import { localizedStatusLabel, productStatus } from '../../lib/presentation';
import { getPlatformDashboardRuntime, platformCapabilityAvailable, type PlatformDashboardRuntime } from '../../lib/platform-dashboard-api';
import { useOrganization } from '../organization/OrganizationContext';

type HomeState = {
  dashboard: PlatformDashboardRuntime | null;
  documents: DocumentRegistryItem[] | null;
  conversations: AssistantConversationItem[] | null;
  governance: GovernanceCenterRuntime | null;
  installation: InstallationStatus | null;
};

export function PlatformHome() {
  const { t } = useI18n();
  const { organization, assistantCapabilities, capabilitiesError, capabilitiesErrorStatus, capabilitiesLoading, capabilitiesResolved, navigationCapabilities, refreshCapabilities } = useOrganization();
  const [state, setState] = useState<HomeState>({
    dashboard: null,
    documents: null,
    conversations: null,
    governance: null,
    installation: null,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');

  const load = useCallback(async () => {
    if (!organization || capabilitiesLoading || !capabilitiesResolved) return;
    setLoading(true);
    setError(null);
    const [
      dashboardResult,
      documentsResult,
      assistantResult,
      governanceResult,
      installationResult,
    ] = await Promise.allSettled([
      getPlatformDashboardRuntime(),
      navigationCapabilities?.documents.visible ? getDocumentWorkspaceRuntime() : Promise.resolve(null),
      assistantCapabilities?.workspace_available ? getAssistantWorkspaceRuntime(organization.id) : Promise.resolve(null),
      getGovernanceCenterRuntime(),
      installationSetupApi.status(),
    ]);
    setState({
      dashboard: dashboardResult.status === 'fulfilled' ? dashboardResult.value : null,
      documents: documentsResult.status === 'fulfilled'
        ? documentsResult.value?.document_registry ?? null
        : null,
      conversations: assistantResult.status === 'fulfilled'
        ? assistantResult.value?.conversations ?? null
        : null,
      governance: governanceResult.status === 'fulfilled' ? governanceResult.value : null,
      installation: installationResult.status === 'fulfilled' ? installationResult.value : null,
    });
    if ([dashboardResult, documentsResult].every((result) => result.status === 'rejected')) {
      setError(t('copy.your_workspace_summary_could_not_be_loaded_the_prima_5ddd08c0'));
    }
    setLoading(false);
  }, [assistantCapabilities?.workspace_available, capabilitiesLoading, capabilitiesResolved, navigationCapabilities?.documents.visible, organization, t]);

  useEffect(() => { void load(); }, [load]);

  function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const prepared = query.trim();
    if (prepared) window.location.assign(`/search?q=${encodeURIComponent(prepared)}`);
  }

  const governanceDiagnostics = useMemo(
    () => normalizeGovernanceDiagnostics(state.governance?.diagnostics),
    [state.governance],
  );
  const operationalBlockers = governanceDiagnostics.operationalBlockers.length;
  const nonBlockingDegradations = governanceDiagnostics.nonBlockingDegradations.length;
  const administrativeReviews = governanceDiagnostics.administrativeReviews.length;
  const recentDocuments = state.documents?.slice(0, 5) ?? [];
  const recentConversations = state.conversations?.slice(0, 5) ?? [];
  const hasActivity = Boolean(state.documents?.length || state.conversations?.length);
  const activitySourcesAvailable = state.documents !== null && state.conversations !== null;
  const searchSection = state.dashboard?.dashboard_sections?.enterprise_search ?? {};
  const persistedSearchReady = state.documents?.some((document) => document.readiness.search_ready === true);
  const searchAvailable = state.dashboard
    ? state.dashboard.readiness_summary.search_ready
    : persistedSearchReady;

  return (
    <div className="product-home">
      <header className="home-welcome">
        <span className="eyebrow">{organization?.name}</span>
        <h1><LocalizedText id="copy.find_and_use_your_organization_s_knowledge_b30c6035" /></h1>
        <p><LocalizedText id="copy.add_governed_documents_search_what_is_available_or_a_3e897a4a" /></p>
      </header>

      <form className="home-search" onSubmit={search}>
        <label className="sr-only" htmlFor="home-search"><LocalizedText id="copy.search_enterprise_knowledge_4d55e169" /></label>
        <input id="home-search" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('copy.search_enterprise_knowledge_4d55e169')} />
        <button className="button" disabled={!query.trim() || !navigationCapabilities?.search.action_available} title={navigationCapabilities?.search.action_available ? undefined : t('dynamic.searchAccessRequired')} type="submit"><LocalizedText id="pages.search.title" /></button>
      </form>

      <section className="home-primary-actions" aria-label={t('copy.primary_actions_48891a63')}>
        {capabilitiesResolved && navigationCapabilities?.documents.action_available ? <a className="primary-action" href="/documents#add-documents"><span><LocalizedText id="shell.stepDocuments" /></span><small><LocalizedText id="copy.upload_and_process_governed_content_cddc8f08" /></small></a> : <span aria-disabled="true" className="primary-action is-disabled" title={capabilitiesResolved ? t('dynamic.documentAdministrationRequired') : t('dynamic.accessEvaluating')}><span><LocalizedText id="shell.stepDocuments" /></span><small>{capabilitiesResolved ? <LocalizedText id="copy.document_administration_access_is_required_92ad604f" /> : <LocalizedText id="copy.checking_access_c5108c02" />}</small></span>}
        {capabilitiesResolved && assistantCapabilities?.workspace_available ? <a className="primary-action" href="/ask"><span><LocalizedText id="copy.ask_a_question_cf94bdf3" /></span><small><LocalizedText id="copy.start_or_continue_an_assistant_conversation_14aed0a8" /></small></a> : <span aria-disabled="true" className="primary-action is-disabled" title={capabilitiesResolved ? t('dynamic.assistantAccessUnavailable') : t('dynamic.accessEvaluating')}><span><LocalizedText id="copy.ask_a_question_cf94bdf3" /></span><small>{capabilitiesResolved ? <LocalizedText id="copy.assistant_access_is_required_9f7426cd" /> : <LocalizedText id="copy.checking_access_c5108c02" />}</small></span>}
      </section>

      {capabilitiesError && !capabilitiesResolved ? <section className="card inline-state"><div><h2><LocalizedText id={capabilitiesErrorStatus === 403 ? 'copy.access_required_3d2f1a2e' : 'copy.access_could_not_be_evaluated_d4d8e1b3'} /></h2><p>{capabilitiesError}</p></div>{capabilitiesErrorStatus === 403 ? <a className="button secondary" href="/security"><LocalizedText id="copy.open_users_access_471c8985" /></a> : <button className="button secondary" type="button" onClick={() => void refreshCapabilities()}><LocalizedText id="common.actions.retry" /></button>}</section> : null}

      {!hasActivity && activitySourcesAvailable && !loading ? (
        <section className="card onboarding-card">
          <div><span className="eyebrow"><LocalizedText id="copy.getting_started_76e7a3a3" /></span><h2><LocalizedText id="copy.set_up_your_knowledge_workspace_900bb64d" /></h2><p><LocalizedText id="copy.progress_is_based_on_persisted_platform_evidence_2cab5185" /></p></div>
          <ol className="onboarding-steps">
            <li className={state.installation?.steps.organization_configured ? 'is-ready' : undefined}>
              {t('setup.gettingStarted.organization')}
            </li>
            <li className={state.installation?.steps.administrator_configured ? 'is-ready' : undefined}>
              {t('setup.gettingStarted.administrator')}
            </li>
            <li className={state.documents?.length ? 'is-ready' : undefined}>
              <LocalizedText id="shell.stepDocuments" />
            </li>
            <li
              className={(
                Number(searchSection.search_requests ?? 0) > 0
                || Boolean(state.conversations?.length)
              ) ? 'is-ready' : undefined}
            >
              <LocalizedText id="copy.search_or_ask_a_question_daf2a9cb" />
            </li>
          </ol>
        </section>
      ) : null}

      {error ? <p className="context-message context-error" role="alert">{error}</p> : null}
      {loading ? <p className="context-message" role="status"><LocalizedText id="copy.loading_recent_work_and_items_needing_attention_cd7bdb9a" /></p> : null}

      <section className="home-section">
        <div className="home-section-heading"><div><h2>{t('home.operationalStatus')}</h2><p>{t('home.operationalStatusHelp')}</p></div>{capabilitiesResolved && platformCapabilityAvailable(navigationCapabilities, 'operations') ? <a className="text-link" href="/operations"><LocalizedText id="pages.operations.title" /></a> : <span aria-disabled="true" className="text-link is-disabled" title={t('navigation.platformPermissionRequired')}><LocalizedText id="pages.operations.title" /></span>}</div>
        {!state.governance && !loading ? <div className="empty-state compact"><strong>{t('home.operationalStatusUnavailable')}</strong><p>{t('home.operationalStatusUnavailableHelp')}</p></div> : operationalBlockers === 0 ? <div className="empty-state compact"><strong>{t('home.dailyWorkAvailable')}</strong><p>{t('home.dailyWorkAvailableHelp')}</p></div> : <div className="attention-list"><article><span className="product-status product-status-failed">{t('home.operationalBlocker')}</span><p>{t('home.operationalBlockerCount', { count: operationalBlockers })}</p></article></div>}
      </section>

      {nonBlockingDegradations > 0 || administrativeReviews > 0 ? (
        <section className="home-section home-governance-notice">
          <div className="home-section-heading"><div><h2>{t('home.governancePending')}</h2><p>{t('home.governancePendingHelp')}</p></div><a className="text-link" href="/governance">{t('home.openGovernance')}</a></div>
          <div className="attention-list">
            {nonBlockingDegradations > 0 ? <article><span className="product-status product-status-attention">{t('governanceUx.groups.nonBlockingDegradation')}</span><p>{t('home.governanceDegradationCount', { count: nonBlockingDegradations })}</p></article> : null}
            {administrativeReviews > 0 ? <article><span className="product-status product-status-neutral">{t('governanceUx.groups.administrativeReview')}</span><p>{t('home.governanceReviewCount', { count: administrativeReviews })}</p></article> : null}
          </div>
          <p>{t('home.governanceDoesNotNecessarilyBlock')}</p>
        </section>
      ) : null}

      <div className="home-recent-grid">
        <section className="home-section">
          <div className="home-section-heading"><div><h2><LocalizedText id="copy.recent_documents_0b072ecf" /></h2><p>{loading ? '—' : state.documents === null ? t('status.unavailable') : t('dynamic.registeredDocumentCount', { count: state.documents.length, value: state.documents.length })}</p></div><a className="text-link" href="/documents"><LocalizedText id="copy.view_all_931e1a4b" /></a></div>
          {state.documents === null ? <div className="empty-state compact"><strong>{t('home.documentsUnavailable')}</strong><p>{t('home.documentsUnavailableHelp')}</p></div> : recentDocuments.length === 0 ? <div className="empty-state compact"><strong><LocalizedText id="copy.no_documents_yet_1837bb99" /></strong><p><LocalizedText id="copy.add_your_first_document_to_start_building_governed_k_7a8b0ffc" /></p>{navigationCapabilities?.documents.action_available ? <a className="button" href="/documents#add-documents"><LocalizedText id="copy.add_your_first_document_cc059937" /></a> : null}</div> : <div className="recent-list">{recentDocuments.map((document) => <a href={`/documents#document-${document.document_record_id}`} key={document.document_record_id}><span><strong>{document.title}</strong><small>{<LocalizedDate value={document.latest_activity} />}</small></span><span className={`product-status product-status-${productStatus(document.lifecycle_status)}`}>{localizedStatusLabel(document.lifecycle_status, t)}</span></a>)}</div>}
        </section>
        <section className="home-section">
          <div className="home-section-heading"><div><h2><LocalizedText id="copy.recent_conversations_2eff3a41" /></h2><p>{loading ? '—' : state.conversations === null ? t('status.unavailable') : t('dynamic.historyConversationCount', { count: state.conversations.length, value: state.conversations.length })}</p></div>{assistantCapabilities?.conversations_available ? <a className="text-link" href="/ask#conversation-history"><LocalizedText id="copy.view_history_dd8f3bf9" /></a> : null}</div>
          {state.conversations === null ? <div className="empty-state compact"><strong>{t('home.conversationsUnavailable')}</strong><p>{t('home.conversationsUnavailableHelp')}</p></div> : recentConversations.length === 0 ? <div className="empty-state compact"><strong><LocalizedText id="copy.no_conversations_yet_f58811ba" /></strong><p><LocalizedText id="copy.ask_your_first_question_using_an_authorized_assistan_0ad2dc30" /></p>{assistantCapabilities?.chat_available ? <a className="button" href="/ask"><LocalizedText id="copy.ask_your_first_question_1e1900fb" /></a> : null}</div> : <div className="recent-list">{recentConversations.map((conversation) => <a href={`/ask?conversation=${conversation.conversation_id}`} key={conversation.conversation_id}><span><strong>{conversation.title ?? t('dynamic.newConversation')}</strong><small>{<LocalizedDate value={conversation.last_activity_at} />}</small></span><span>{t('dynamic.turnCount', { count: conversation.turn_count, value: conversation.turn_count })}</span></a>)}</div>}
        </section>
      </div>

      <section className="workspace-summary-strip home-activity" aria-label={t('copy.activity_summary_70f4ec76')}>
        <div><small><LocalizedText id="pages.documents.title" /></small><strong>{loading ? '—' : state.documents === null ? t('status.unavailable') : state.documents.length}</strong></div>
        <div><small><LocalizedText id="copy.conversations_07c59b44" /></small><strong>{loading ? '—' : state.conversations === null ? t('status.unavailable') : state.conversations.length}</strong></div>
        <div><small><LocalizedText id="copy.searches_450d52d3" /></small><strong>{loading ? '—' : state.dashboard ? String(searchSection.search_requests ?? 0) : t('status.unavailable')}</strong></div>
        <div><small><LocalizedText id="copy.search_availability_36ecf147" /></small><strong>{loading ? '—' : localizedStatusLabel(searchAvailable, t)}</strong></div>
      </section>
    </div>
  );
}
