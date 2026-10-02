'use client';

import { useI18n } from '../../i18n/I18nProvider';

import { LocalizedText } from '../layout/LocalizedText';

import { type FormEvent, useEffect, useMemo, useRef, useState } from 'react';

import {
  executeEnterpriseSearch,
  getSearchDiscoveryRuntime,
  type EnterpriseSearchResponse,
  type EnterpriseSearchResult,
  type SearchDiscoveryRuntime,
} from '../../lib/search-discovery-api';
import {
  localizedApiError,
  localizedProductLabel,
  localizedStatusLabel,
} from '../../lib/presentation';
import { useOrganization } from '../organization/OrganizationContext';

function asText(value: unknown, fallback = '-'): string {
  if (value === null || value === undefined || value === '') return fallback;
  return String(value);
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function asList(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((item) => item && typeof item === 'object') as Record<string, unknown>[]
    : [];
}

function statusClass(ready: boolean): string {
  return ready ? 'status-dot ready' : 'status-dot degraded';
}

function issueText(item: Record<string, unknown>, translate: (key: string) => string): string {
  return asText(item.message ?? item.label ?? item.reason ?? item.code, translate('dynamic.detailsAvailable'));
}

function readableContentType(value: unknown): string {
  return asText(value).replaceAll('_', ' ');
}

function resultMetadata(result: EnterpriseSearchResult): Record<string, unknown> {
  return asRecord(result.metadata);
}

function nestedMetadata(result: EnterpriseSearchResult): Record<string, unknown> {
  return asRecord(resultMetadata(result).document_metadata);
}

function resultTitle(result: EnterpriseSearchResult, fallback: string): string {
  const metadata = resultMetadata(result);
  const documentMetadata = nestedMetadata(result);
  return asText(
    metadata.document_title
      ?? documentMetadata.title
      ?? metadata.original_filename
      ?? documentMetadata.file_name
      ?? metadata.file_name,
    fallback,
  );
}

function resultCollection(result: EnterpriseSearchResult, fallback: string): string {
  const metadata = resultMetadata(result);
  const documentMetadata = nestedMetadata(result);
  return asText(
    metadata.collection_name
      ?? documentMetadata.collection_name
      ?? documentMetadata.collection_code
      ?? metadata.collection_code,
    fallback,
  );
}

function resultDocumentType(result: EnterpriseSearchResult, fallback: string): string {
  const metadata = resultMetadata(result);
  return asText(metadata.document_type_name ?? metadata.document_content_type ?? result.content_type, fallback);
}

function resultDocumentId(result: EnterpriseSearchResult): string | null {
  const metadata = resultMetadata(result);
  const documentMetadata = nestedMetadata(result);
  const value = metadata.document_record_id ?? documentMetadata.document_record_id;
  return typeof value === 'string' && value ? value : null;
}

function SafeHighlightedSnippet({ value }: { value: string }) {
  const parts = value.split(/(<mark>|<\/mark>)/gi);
  let highlighted = false;
  let highlightIndex = 0;
  return (
    <p>
      {parts.map((part, index) => {
        if (part.toLowerCase() === '<mark>') {
          highlighted = true;
          return null;
        }
        if (part.toLowerCase() === '</mark>') {
          highlighted = false;
          return null;
        }
        if (!part) return null;
        if (highlighted) {
          highlightIndex += 1;
          return <mark key={`highlight-${highlightIndex}-${index}`}>{part}</mark>;
        }
        return <span key={`text-${index}`}>{part}</span>;
      })}
    </p>
  );
}

function EnterpriseSearchQuery({ contentTypes }: { contentTypes: string[] }) {
  const { t } = useI18n();
  const [query, setQuery] = useState('');
  const [search, setSearch] = useState<EnterpriseSearchResponse | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [contentType, setContentType] = useState('');
  const initialQueryHandled = useRef(false);
  const searchInFlight = useRef(false);

  async function runSearch(normalized: string) {
    if (!normalized || searchInFlight.current) return;
    searchInFlight.current = true;
    setSearching(true);
    setSearchError(null);
    try {
      setSearch(await executeEnterpriseSearch(normalized, contentType));
    } catch (cause) {
      setSearch(null);
      setSearchError(localizedApiError(cause, t, 'feedback.enterpriseSearchQueryFailed'));
    } finally {
      searchInFlight.current = false;
      setSearching(false);
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runSearch(query.trim());
  }

  useEffect(() => {
    if (initialQueryHandled.current) return;
    initialQueryHandled.current = true;
    const initialQuery = new URLSearchParams(window.location.search).get('q')?.trim() ?? '';
    if (initialQuery) {
      setQuery(initialQuery);
      void runSearch(initialQuery);
    }
  // The initial URL query is intentionally executed once to avoid duplicate persisted search records.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <section className="table-card primary-search" data-search-discovery-section="query">
      <div className="section-header">
        <div>
          <span className="eyebrow"><LocalizedText id="copy.enterprise_knowledge_8680743e" /></span>
          <h2><LocalizedText id="copy.what_are_you_looking_for_ffca59bc" /></h2>
          <p id="enterprise-search-help"><LocalizedText id="copy.search_uses_governed_content_from_the_active_organiz_38671a4f" /></p>
        </div>
      </div>
      <form className="search-query-form" onSubmit={submit}>
        <div className="search-query-controls">
          <label className="sr-only" htmlFor="enterprise-search-query"><LocalizedText id="pages.search.title" /></label>
          <input
            autoComplete="off"
            aria-describedby="enterprise-search-help"
            className="field-control"
            id="enterprise-search-query"
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t('copy.search_documents_procedures_and_governed_knowledge_6c7f2aff')}
            type="search"
            value={query}
          />
          <button className="button" disabled={searching || !query.trim()} type="submit">
            {searching ? <LocalizedText id="copy.searching_1a6a5ba8" /> : <LocalizedText id="pages.search.title" />}
          </button>
        </div>
        {contentTypes.length > 0 ? (
          <div className="basic-filters">
            <label className="field-label" htmlFor="search-content-type"><LocalizedText id="copy.content_type_de15f753" /></label>
            <select className="field-control" id="search-content-type" value={contentType} onChange={(event) => setContentType(event.target.value)}>
              <option value=""><LocalizedText id="copy.all_content_types_626a5b9c" /></option>
              {contentTypes.map((value) => <option key={value} value={value}>{readableContentType(value)}</option>)}
            </select>
          </div>
        ) : null}
      </form>
      {!searching && !search && !searchError ? (
        <div className="empty-state"><strong><LocalizedText id="copy.enter_a_query_to_begin_4aaecef5" /></strong><p><LocalizedText id="copy.no_ai_service_is_required_91b03ad1" /></p></div>
      ) : null}
      {searching ? <div className="empty-state" aria-live="polite"><strong><LocalizedText id="copy.searching_governed_knowledge_dca431a7" /></strong></div> : null}
      {searchError ? (
        <div className="context-message context-error" role="alert">
          <strong><LocalizedText id="copy.search_could_not_be_completed_27607ec6" /></strong> {searchError}
        </div>
      ) : null}
      {search && search.results.length === 0 ? (
        <div className="empty-state">
          <strong><LocalizedText id="copy.no_matching_results_274c15f9" /></strong>
          <p><LocalizedText id="copy.try_a_different_term_or_confirm_that_the_selected_or_bc947f8a" /></p>
        </div>
      ) : null}
      {search && search.results.length > 0 ? (
        <div className="search-results" aria-live="polite">
          <p className="search-result-count">{t('dynamic.resultCount', { count: search.total_count, value: search.total_count })}</p>
          {search.results.map((result) => (
            <article className="context-card search-result" key={result.search_result_id}>
              <div className="context-card-header">
                <div>
                  <small>{t('dynamic.resultRank', { number: result.rank })}</small>
                  <h3>{resultDocumentId(result) ? <a href={`/documents#document-${resultDocumentId(result)}`}>{resultTitle(result, t('search.governedDocument'))}</a> : resultTitle(result, t('search.governedDocument'))}</h3>
                </div>
                <span className="status-pill">{resultDocumentType(result, t('search.document'))}</span>
              </div>
              <SafeHighlightedSnippet value={result.highlighted_snippet || result.snippet || result.text} />
              <p className="muted-text">{resultCollection(result, t('search.governedCollection'))}</p>
              {resultDocumentId(result) ? <a className="text-link" href={`/documents#document-${resultDocumentId(result)}`}><LocalizedText id="copy.open_source_document_964e6aef" /></a> : <span className="muted-text"><LocalizedText id="copy.the_source_document_is_not_available_from_this_resul_2c118f61" /></span>}
              <details>
                <summary><LocalizedText id="common.advancedDetails" /></summary>
                <dl className="technical-details-grid">
                  <dt><LocalizedText id="copy.relevance_dcb70f52" /></dt><dd>{result.score.toFixed(3)}</dd>
                  <dt><LocalizedText id="copy.result_id_49964741" /></dt><dd>{result.search_result_id}</dd>
                  <dt><LocalizedText id="copy.published_chunk_f7c01943" /></dt><dd>{asText(result.published_chunk_id)}</dd>
                  <dt><LocalizedText id="copy.publication_e00441c4" /></dt><dd>{asText(result.publication_id)}</dd>
                  <dt><LocalizedText id="copy.artifact_aa778b50" /></dt><dd>{asText(result.artifact_id)}</dd>
                  <dt><LocalizedText id="copy.citation_id_8c1a4586" /></dt><dd>{asText(result.citation?.citation_id)}</dd>
                </dl>
              </details>
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function MetricCard({ label, value }: { label: string; value: unknown }) {
  const { t } = useI18n();
  return (
    <article className="metric-card">
      <small>{label}</small>
      <strong>{typeof value === 'boolean'
        ? localizedStatusLabel(value, t)
        : localizedProductLabel(value, t, '0')}</strong>
    </article>
  );
}

function Summary({ runtime }: { runtime: SearchDiscoveryRuntime }) {
  const { t } = useI18n();
  const summary = runtime.workspace_summary ?? {};
  const search = runtime.enterprise_search_summary ?? {};
  const coverage = runtime.knowledge_coverage ?? {};
  return (
    <section className="grid" data-search-discovery-section="summary">
      <article className="card health-card">
        <div className="context-card-header">
          <h2><LocalizedText id="copy.search_ready_028329ac" /></h2>
          <span className={statusClass(Boolean(summary.search_ready))}></span>
        </div>
        <span className="metric-value">{localizedStatusLabel(summary.search_ready, t)}</span>
      </article>
      <MetricCard label={t('copy.indexed_documents_21aeb5c3')} value={search.indexed_document_count} />
      <MetricCard label={t('copy.searchable_chunks_6e4237c0')} value={search.searchable_chunk_count} />
      <MetricCard label={t('copy.collections_4bbb632f')} value={coverage.collection_count} />
      <MetricCard label={t('copy.knowledge_documents_e25dbfc5')} value={coverage.knowledge_document_count} />
      <MetricCard label={t('copy.indexed_chunks_86bc1069')} value={coverage.indexed_chunks} />
      <MetricCard label={t('copy.document_coverage_8b1eb399')} value={coverage.document_coverage} />
      <MetricCard label={t('copy.quality_score_9ee51142')} value={asRecord(runtime.search_quality).quality_score} />
    </section>
  );
}

function CollectionSourceSection({ runtime }: { runtime: SearchDiscoveryRuntime }) {
  const { t } = useI18n();
  return (
    <section className="table-card" data-search-discovery-section="knowledge-explorer">
      <h2><LocalizedText id="copy.knowledge_explorer_72da6167" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.collections_4bbb632f')} value={runtime.knowledge_collections.length} />
        <MetricCard label={t('ask.sources')} value={runtime.knowledge_sources.length} />
        <MetricCard label={t('pages.documents.title')} value={runtime.knowledge_documents.length} />
        <MetricCard label={t('copy.chunks_4a527377')} value={asRecord(runtime.knowledge_chunks).total_chunks} />
      </div>
      <table>
        <thead>
          <tr><th><LocalizedText id="copy.collection_30c54a96" /></th><th><LocalizedText id="common.status" /></th><th><LocalizedText id="pages.documents.title" /></th><th><LocalizedText id="copy.chunks_4a527377" /></th><th><LocalizedText id="copy.readiness_6dc1222c" /></th></tr>
        </thead>
        <tbody>
          {runtime.knowledge_collections.map((collection) => (
            <tr key={asText(collection.collection_id)}>
              <td>{asText(collection.name)}<br /><small>{asText(collection.code)}</small></td>
              <td>{localizedStatusLabel(collection.status, t)}</td>
              <td>{asText(collection.knowledge_document_count, '0')}</td>
              <td>{asText(collection.chunk_count, '0')}</td>
              <td>{localizedStatusLabel(asRecord(collection.readiness).status, t)}</td>
            </tr>
          ))}
          {runtime.knowledge_collections.length === 0 ? <tr><td className="table-empty" colSpan={5}><LocalizedText id="common.noItems" /></td></tr> : null}
        </tbody>
      </table>
    </section>
  );
}

function DocumentChunkSection({ runtime }: { runtime: SearchDiscoveryRuntime }) {
  const { t } = useI18n();
  const documentExplorer = asRecord(runtime.document_explorer);
  const chunkExplorer = asRecord(runtime.chunk_explorer);
  const documents = asList(documentExplorer.documents);
  const chunks = asList(chunkExplorer.sample_chunks);
  return (
    <section className="table-card" data-search-discovery-section="document-chunk-explorer">
      <h2><LocalizedText id="copy.document_and_chunk_explorer_a77ee89f" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('pages.documents.title')} value={documentExplorer.document_count} />
        <MetricCard label={t('copy.versions_a239107e')} value={documentExplorer.version_count} />
        <MetricCard label={t('copy.searchable_documents_4cf5fdb6')} value={documentExplorer.searchable_documents} />
        <MetricCard label={t('copy.sample_chunks_2c13696e')} value={chunks.length} />
      </div>
      <table>
        <thead>
          <tr><th><LocalizedText id="copy.document_e214b8a2" /></th><th><LocalizedText id="common.status" /></th><th><LocalizedText id="copy.collection_30c54a96" /></th><th><LocalizedText id="pages.search.title" /></th><th><LocalizedText id="copy.chat_2ced57f1" /></th></tr>
        </thead>
        <tbody>
          {documents.slice(0, 10).map((document) => {
            const readiness = asRecord(document.readiness);
            const collection = asRecord(document.collection);
            return (
              <tr key={asText(document.document_record_id)}>
                <td>{asText(document.title)}</td>
                <td>{localizedStatusLabel(document.status, t)}</td>
                <td>{asText(collection.name)}</td>
                <td>{localizedStatusLabel(readiness.search_ready, t)}</td>
                <td>{localizedStatusLabel(readiness.chat_ready, t)}</td>
              </tr>
            );
          })}
          {documents.length === 0 ? <tr><td className="table-empty" colSpan={5}><LocalizedText id="common.noItems" /></td></tr> : null}
        </tbody>
      </table>
    </section>
  );
}

function DiscoveryDiagnostics({ runtime }: { runtime: SearchDiscoveryRuntime }) {
  const { t } = useI18n();
  const groups = [
    [t('search.diagnostics.search'), asList(asRecord(runtime.search_diagnostics).degraded_items)],
    [t('search.diagnostics.coverage'), asList(asRecord(runtime.coverage_diagnostics).warnings)],
    [t('search.diagnostics.pending'), runtime.pending_capabilities],
    [t('search.diagnostics.recommendations'), runtime.recommendations],
  ];
  return (
    <section className="table-card" data-search-discovery-section="diagnostics">
      <h2><LocalizedText id="copy.diagnostics_evidence_and_traceability_0c2f6f99" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.evidence_ready_3b472c58')} value={asRecord(runtime.evidence_readiness).evidence_ready} />
        <MetricCard label={t('copy.citation_count_28d97e62')} value={asRecord(runtime.evidence_readiness).citation_count} />
        <MetricCard label={t('copy.runtime_trace_43630593')} value={asRecord(runtime.traceability).runtime_trace_available} />
        <MetricCard label={t('copy.reference_search_4c8cfd06')} value={asRecord(runtime.reference_tenant_coverage).reference_search_ready} />
      </div>
      <div className="alerts-grid">
        {groups.map(([label, values]) => (
          <article className="context-card" key={label as string}>
            <div className="context-card-header">
              <strong>{label as string}</strong>
              <span>{(values as Record<string, unknown>[]).length}</span>
            </div>
            {(values as Record<string, unknown>[]).length > 0 ? (
              <ul className="compact-list">
                {(values as Record<string, unknown>[]).slice(0, 8).map((item, index) => (
                  <li key={`${label}-${index}`}>{issueText(item, t)}</li>
                ))}
              </ul>
            ) : (
              <p><LocalizedText id="common.noItems" /></p>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

export function SearchDiscoveryWorkspace() {
  const { t } = useI18n();
  const { capabilitiesError, capabilitiesErrorStatus, capabilitiesLoading, capabilitiesResolved, navigationCapabilities, refreshCapabilities } = useOrganization();
  const [runtime, setRuntime] = useState<SearchDiscoveryRuntime | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (capabilitiesLoading || !capabilitiesResolved) return;
    if (!navigationCapabilities?.search.visible) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const payload = await getSearchDiscoveryRuntime();
        if (!cancelled) setRuntime(payload);
      } catch (loadError) {
        if (!cancelled) {
          setError(localizedApiError(loadError, t, 'feedback.searchDiscoveryRuntimeUnavailable'));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [capabilitiesLoading, capabilitiesResolved, navigationCapabilities?.search.visible, t]);

  const summary = useMemo(() => runtime?.workspace_summary ?? {}, [runtime]);

  const contentTypes = runtime
    ? Array.from(new Set(runtime.knowledge_documents.map((document) => asText(document.content_type, '')).filter(Boolean)))
    : [];

  if (!capabilitiesResolved && capabilitiesLoading) {
    return <section className="card workspace-state"><h2><LocalizedText id="copy.loading_search_329d24cf" /></h2><p><LocalizedText id="copy.evaluating_authorized_knowledge_access_for_the_activ_a87cf28c" /></p></section>;
  }

  if (capabilitiesError && !capabilitiesResolved) {
    return <section className="card workspace-state"><h2><LocalizedText id={capabilitiesErrorStatus === 403 ? 'copy.access_required_3d2f1a2e' : 'copy.search_access_could_not_be_evaluated_c532c26d'} /></h2><p>{capabilitiesError}</p>{capabilitiesErrorStatus === 403 ? <a className="button secondary" href="/security"><LocalizedText id="copy.open_users_access_471c8985" /></a> : <button className="button secondary" type="button" onClick={() => void refreshCapabilities()}><LocalizedText id="common.actions.retry" /></button>}</section>;
  }

  if (capabilitiesResolved && !capabilitiesLoading && !navigationCapabilities?.search.visible) {
    return <section className="card workspace-state"><span className="eyebrow"><LocalizedText id="copy.access_required_3d2f1a2e" /></span><h2><LocalizedText id="copy.search_is_unavailable_for_your_account_758b056f" /></h2><p><LocalizedText id="copy.an_organization_administrator_must_grant_knowledge_c_51ea6e96" /></p><a className="button secondary" href="/security"><LocalizedText id="copy.open_users_access_471c8985" /></a></section>;
  }

  return (
    <div className="product-workspace" data-search-discovery={runtime ? 'ready' : loading ? 'loading' : 'partially-configured'}>
      <EnterpriseSearchQuery contentTypes={contentTypes} />
      {loading ? <p className="context-message" role="status"><LocalizedText id="copy.loading_search_status_4ad93ebb" /></p> : null}
      {error ? <section className="card inline-state" data-search-discovery-section="error"><div><h2><LocalizedText id="copy.search_status_is_unavailable_2dbc7629" /></h2><p><LocalizedText id="copy.you_can_still_submit_a_query_an_administrator_can_re_d877b6a8" /></p></div></section> : null}
      {runtime && !Boolean(summary.search_ready) ? <section className="card inline-state"><div><h2><LocalizedText id="copy.search_is_not_fully_ready_e1898d0a" /></h2><p><LocalizedText id="copy.add_and_process_documents_then_review_search_status__7531b5b8" /></p></div><a className="button" href="/documents#add-documents"><LocalizedText id="shell.stepDocuments" /></a></section> : null}
      {runtime ? (
        <details className="advanced-panel">
          <summary><LocalizedText id="copy.search_status_and_advanced_diagnostics_5e8c3d6f" /></summary>
          <div className="advanced-panel-content">
            <Summary runtime={runtime} />
            <CollectionSourceSection runtime={runtime} />
            <DocumentChunkSection runtime={runtime} />
            <DiscoveryDiagnostics runtime={runtime} />
          </div>
        </details>
      ) : null}
    </div>
  );
}
