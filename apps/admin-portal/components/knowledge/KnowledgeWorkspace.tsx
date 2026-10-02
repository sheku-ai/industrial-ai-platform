'use client';

import { LocalizedDate, LocalizedText } from '../layout/LocalizedText';

import { useI18n } from '../../i18n/I18nProvider';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { getKnowledgeWorkspaceRuntime, type KnowledgeWorkspaceRuntime } from '../../lib/knowledge-workspace-api';
import { issueMessage, localizedProductLabel, productStatus } from '../../lib/presentation';
import { useOrganization } from '../organization/OrganizationContext';

function value(value: unknown, fallback = '0'): string {
  return value === null || value === undefined || value === '' ? fallback : String(value);
}

export function KnowledgeWorkspace() {
  const { t } = useI18n();
  const { organization } = useOrganization();
  const [runtime, setRuntime] = useState<KnowledgeWorkspaceRuntime | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestVersion = useRef(0);

  const load = useCallback(async () => {
    const version = ++requestVersion.current;
    setLoading(true);
    setError(null);
    try {
      const payload = await getKnowledgeWorkspaceRuntime();
      if (version === requestVersion.current) setRuntime(payload);
    }
    catch (cause) {
      if (version === requestVersion.current) {
        setError(cause instanceof Error ? cause.message : t('feedback.knowledgeLoadFailed'));
      }
    }
    finally { if (version === requestVersion.current) setLoading(false); }
  }, [t]);

  useEffect(() => {
    setRuntime(null);
    void load();
    return () => { requestVersion.current += 1; };
  }, [load, organization?.id]);

  const diagnostics = useMemo(() => runtime ? [...(runtime.diagnostics.blocking_issues ?? []), ...(runtime.diagnostics.warnings ?? []), ...(runtime.diagnostics.pending_capabilities ?? [])] : [], [runtime]);

  if (loading && !runtime) return <section className="card workspace-state"><h2><LocalizedText id="copy.loading_knowledge_892e6ec9" /></h2><p><LocalizedText id="copy.retrieving_published_and_indexed_knowledge_for_the_a_4c26a4c8" /></p></section>;
  if (!runtime) return <section className="card workspace-state"><h2><LocalizedText id="copy.knowledge_unavailable_59c0b4cf" /></h2><p>{error ?? <LocalizedText id="copy.no_knowledge_state_was_returned_dfa13d7a" />}</p><button className="button secondary" type="button" onClick={() => void load()}><LocalizedText id="common.actions.retry" /></button></section>;

  const summary = runtime.workspace_summary ?? {};
  const search = runtime.enterprise_search ?? {};
  const sampleChunks = Array.isArray(runtime.chunk_overview.sample_chunks) ? runtime.chunk_overview.sample_chunks as Record<string, unknown>[] : [];

  return (
    <div className="product-workspace">
      {error ? <p className="context-message context-error" role="alert">{t('dynamic.latestKnowledgeStatusError')} <button className="button secondary" type="button" onClick={() => void load()}><LocalizedText id="common.actions.retry" /></button></p> : null}
      {loading ? <p className="context-message" role="status"><LocalizedText id="copy.refreshing_knowledge_status_fad1c3c0" /></p> : null}
      <p className="context-message">{t('dynamic.knowledgeScope', { organization: organization?.name ?? t('dynamic.selectedOrganization') })}</p>
      <section className="workspace-summary-strip" aria-label={t('copy.knowledge_summary_45f915ba')}>
        <div><small><LocalizedText id="copy.source_documents_1dc30abc" /></small><strong>{value(runtime.collections.reduce((total, collection) => total + collection.document_count, 0))}</strong></div>
        <div><small><LocalizedText id="copy.published_knowledge_8e386cc8" /></small><strong>{runtime.knowledge_documents.length}</strong></div>
        <div><small><LocalizedText id="copy.searchable_documents_4cf5fdb6" /></small><strong>{value(search.indexed_document_count)}</strong></div>
        <div><small><LocalizedText id="copy.knowledge_status_84d7e05c" /></small><strong>{localizedProductLabel(summary.knowledge_ready, t)}</strong></div>
      </section>

      <section className="table-card">
        <div className="section-header"><span className="eyebrow"><LocalizedText id="copy.available_knowledge_b4b8b855" /></span><h2><LocalizedText id="copy.published_sources_4853f29b" /></h2><p><LocalizedText id="copy.collections_organize_source_documents_published_know_1d8f8494" /></p></div>
        {runtime.collections.length === 0 ? <div className="empty-state"><strong><LocalizedText id="copy.no_published_knowledge_yet_89ae8bc9" /></strong><p><LocalizedText id="copy.add_and_process_documents_to_publish_the_first_gover_bc56ad14" /></p><a className="button" href="/documents#add-documents"><LocalizedText id="shell.stepDocuments" /></a></div> : <div className="knowledge-collection-list">{runtime.collections.map((collection) => <article key={collection.collection_id}><div><h3>{collection.name}</h3><p>{t('dynamic.collectionKnowledgeCounts', { documents: collection.document_count, published: collection.knowledge_document_count, passages: collection.chunk_count })}</p></div><span className={`product-status product-status-${productStatus((collection.readiness as Record<string, unknown>).status)}`}>{localizedProductLabel((collection.readiness as Record<string, unknown>).status, t)}</span></article>)}</div>}
      </section>

      <section className="table-card">
        <h2><LocalizedText id="copy.knowledge_documents_e25dbfc5" /></h2>
        {runtime.knowledge_documents.length === 0 ? <p className="muted-text"><LocalizedText id="copy.no_document_has_completed_knowledge_publication_952d4c21" /></p> : <table><thead><tr><th><LocalizedText id="copy.document_e214b8a2" /></th><th><LocalizedText id="copy.publication_e00441c4" /></th><th><LocalizedText id="copy.searchable_content_65f953fa" /></th><th><LocalizedText id="status.published" /></th><th><LocalizedText id="copy.source_6da13add" /></th></tr></thead><tbody>{runtime.knowledge_documents.map((document) => <tr key={document.knowledge_document_id}><td>{document.title ?? t('dynamic.untitledDocument')}</td><td><span className={`product-status product-status-${productStatus(document.status)}`}>{localizedProductLabel(document.status, t)}</span></td><td>{t('dynamic.passageCount', { count: document.chunk_count, value: document.chunk_count })}</td><td>{<LocalizedDate value={document.indexed_at ?? document.created_at} />}</td><td>{document.document_record_id ? <a className="text-link" href={`/documents#document-${document.document_record_id}`}><LocalizedText id="copy.open_document_5fc7f210" /></a> : t('common.notAvailable')}</td></tr>)}</tbody></table>}
      </section>

      <details className="advanced-panel"><summary><LocalizedText id="copy.advanced_knowledge_details_8e71b0a2" /></summary><div className="advanced-panel-content">
        <section className="table-card"><h2><LocalizedText id="copy.knowledge_sources_516cf9f9" /></h2><table><thead><tr><th><LocalizedText id="common.type" /></th><th><LocalizedText id="common.status" /></th><th><LocalizedText id="copy.readiness_6dc1222c" /></th><th><LocalizedText id="copy.configuration_75416485" /></th></tr></thead><tbody>{runtime.knowledge_sources.map((source) => <tr key={source.source_id}><td>{localizedProductLabel(source.source_type, t)}</td><td>{localizedProductLabel(source.source_status, t)}</td><td>{localizedProductLabel(source.readiness, t)}</td><td>{source.configured ? <LocalizedText id="status.configured" /> : <LocalizedText id="status.notConfigured" />}</td></tr>)}</tbody></table></section>
        <section className="table-card"><h2><LocalizedText id="copy.indexing_details_2e9fba45" /></h2><div className="metrics-grid"><article className="metric-card"><small><LocalizedText id="copy.searchable_passages_2a7b091d" /></small><strong>{value(search.searchable_chunk_count)}</strong></article><article className="metric-card"><small><LocalizedText id="copy.indexed_passages_32c945c8" /></small><strong>{value(runtime.chunk_overview.indexed_chunks)}</strong></article><article className="metric-card"><small><LocalizedText id="copy.search_status_8ee1d1ed" /></small><strong>{localizedProductLabel(search.search_ready, t)}</strong></article></div>{sampleChunks.length ? <div className="context-list">{sampleChunks.map((chunk, index) => <article className="context-card" key={index}><strong>{localizedProductLabel(chunk.status, t)}</strong><p>{value(chunk.text_preview, t('dynamic.noPreviewAvailable'))}</p></article>)}</div> : null}</section>
        <section className="table-card"><h2><LocalizedText id="copy.diagnostics_3af2279f" /></h2>{diagnostics.length ? <ul className="compact-list">{diagnostics.map((item, index) => <li key={index}>{issueMessage(item, t('dynamic.detailsAvailable'))}</li>)}</ul> : <p className="muted-text"><LocalizedText id="copy.no_diagnostic_items_reported_2e3c0092" /></p>}</section>
      </div></details>
    </div>
  );
}
