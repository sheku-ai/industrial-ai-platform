'use client';

import { useI18n } from '../../i18n/I18nProvider';

import { LocalizedText } from '../layout/LocalizedText';

import { useEffect, useMemo, useState } from 'react';

import {
  getPlatformAdministrationRuntime,
  type PlatformAdministrationRuntime,
} from '../../lib/platform-administration-api';
import { isUuid } from '../../lib/platform-api';
import { localizedProductLabel } from '../../lib/presentation';

type Row = Record<string, unknown>;

function asText(value: unknown, fallback = '—'): string {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'boolean') return value ? 'Enabled' : 'Disabled';
  return String(value);
}

function asList(value: unknown): Row[] {
  return Array.isArray(value) ? (value as Row[]) : [];
}

function asMap(value: unknown): Row {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Row) : {};
}

function statusClass(ready: boolean): string {
  return ready ? 'status-dot ready' : 'status-dot degraded';
}

function issueText(item: Row, translate: (key: string) => string): string {
  return asText(item.message ?? item.reason ?? item.code, translate('dynamic.detailsAvailable'));
}

function CountCard({ label, value, ready = true }: { label: string; value: unknown; ready?: boolean }) {
  return (
    <article className="card health-card">
      <div className="context-card-header">
        <h2>{label}</h2>
        <span className={statusClass(ready)}></span>
      </div>
      <span className="metric-value">{asText(value, '0')}</span>
    </article>
  );
}

function SimpleTable({ title, rows, columns }: { title: string; rows: Row[]; columns: string[] }) {
  const { t } = useI18n();
  const columnKeys: Record<string, string> = {
    assistant_key: 'dynamic.assistantKey', assistant_name: 'dynamic.assistantName', assistant_status: 'dynamic.assistantStatus',
    assistant_version: 'dynamic.assistantVersion', code: 'common.code', enabled: 'common.enabled', guardrail_type: 'dynamic.guardrailType',
    name: 'common.name', node_type: 'dynamic.nodeType', principal: 'dynamic.principalType', principal_type: 'dynamic.principalType',
    role: 'copy.role_c3f104d1', scope_domain: 'dynamic.scopeDomain', source_type: 'dynamic.sourceType',
    status: 'common.status', version: 'dynamic.version', slug: 'dynamic.slug',
  };
  return (
    <section className="table-card">
      <h2>{title}</h2>
      <table>
        <thead>
          <tr>{columns.map((column) => <th key={column}>{t(columnKeys[column] ?? 'common.name')}</th>)}</tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr><td colSpan={columns.length}><LocalizedText id="copy.no_records_reported_by_runtime_36306828" /></td></tr>
          ) : rows.map((row, index) => (
            <tr key={`${title}-${index}`}>
              {columns.map((column) => (
                <td key={column}>
                  {typeof row[column] === 'string' && isUuid(row[column] as string) ? (
                    <details><summary><LocalizedText id="common.technicalId" /></summary><small>{row[column] as string}</small></details>
                  ) : typeof row[column] === 'boolean' || ['status', 'enabled', 'node_type'].includes(column)
                    ? localizedProductLabel(row[column], t)
                    : asText(row[column])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export function AdministrationWorkspace() {
  const { t } = useI18n();
  const [runtime, setRuntime] = useState<PlatformAdministrationRuntime | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [includeValidation, setIncludeValidation] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const payload = await getPlatformAdministrationRuntime(includeValidation);
        if (!cancelled) setRuntime(payload);
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : t('feedback.administrationRuntimeUnavailable'));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [includeValidation, t]);

  const diagnostics = useMemo(() => {
    const health = asMap(runtime?.health_summary);
    const reference = asMap(runtime?.reference_tenant);
    const productBaseline = asMap(reference.product_baseline);
    return {
      blockingIssues: [
        ...(runtime?.blocking_issues ?? []),
        ...asList(productBaseline.blocking_issues),
      ],
      warnings: runtime?.warnings ?? [],
      pendingCapabilities: asList(productBaseline.pending_capabilities),
      degradedDomains: Array.isArray(health.blocking_domains) ? health.blocking_domains as string[] : [],
    };
  }, [runtime]);

  if (loading) {
    return (
      <section className="card" data-administration-workspace-section="loading">
        <h2><LocalizedText id="copy.loading_administration_workspace_f2ca00da" /></h2>
        <p><LocalizedText id="copy.retrieving_platform_configuration_state_from_postgre_27e10121" /></p>
      </section>
    );
  }

  if (error || !runtime) {
    return (
      <section className="card" data-administration-workspace-section="error">
        <h2><LocalizedText id="copy.administration_workspace_unavailable_911cbec9" /></h2>
        <p>{error ?? <LocalizedText id="copy.no_administration_runtime_payload_was_returned_ed29cdf0" />}</p>
      </section>
    );
  }

  const platform = asMap(runtime.platform);
  const metadata = asMap(platform.metadata);
  const configuredCapabilities = asMap(platform.configured_capabilities);
  const installedCapabilities = Array.isArray(platform.installed_capabilities)
    ? platform.installed_capabilities as string[]
    : [];
  const organizations = asMap(runtime.organizations);
  const organizationCounts = asMap(organizations.counts);
  const hierarchy = asMap(organizations.organization_hierarchy);
  const nodes = asList(hierarchy.nodes);
  const rootNodes = nodes.filter((node) => !node.parent_node_id);
  const relationships = asList(hierarchy.relationships);
  const security = asMap(runtime.security);
  const securityTotals = asMap(security.effective_totals);
  const roles = asList(security.roles);
  const assignments = asList(security.assignments).map((assignment) => {
    const principalValue = String(assignment.principal_id ?? '');
    const principal = isUuid(principalValue)
      ? localizedProductLabel(assignment.principal_type, t)
      : principalValue.includes(':') ? principalValue.split(':').pop() : principalValue;
    return {
      ...assignment,
      principal,
      role: roles.find((role) => String(role.id) === String(assignment.role_id))?.name ?? t('copy.role_c3f104d1'),
    };
  });
  const documents = asMap(runtime.documents);
  const knowledge = asMap(runtime.knowledge);
  const assistants = asMap(runtime.assistants);
  const reference = asMap(runtime.reference_tenant);
  const referenceReadiness = asMap(reference.readiness);
  const referenceBaseline = asMap(reference.product_baseline);
  const dataScope = asMap(runtime.data_scope);

  return (
    <div className="platform-home" data-administration-workspace="ready">
      <header className="platform-hero" data-administration-workspace-section="summary">
        <div>
          <span className="badge"><LocalizedText id="copy.platform_governance_240751de" /></span>
          <h2><LocalizedText id="copy.administration_overview_3fb98e5e" /></h2>
          <p><LocalizedText id="copy.organizations_security_document_configuration_knowle_95fdcd1e" /></p>
        </div>
        <div className="platform-status-panel">
          <p><span className={statusClass(runtime.runtime_status === 'ready')}></span> <LocalizedText id="copy.runtime_c4740e4c" />{runtime.runtime_status}</p>
          <p><LocalizedText id="copy.version_9f491270" />{asText(platform.version ?? metadata.product_version)}</p>
          <p><LocalizedText id="copy.edition_014f92c8" />{asText(platform.edition)}</p>
          <p><LocalizedText id="copy.product_baseline_f5869f91" />{asText(referenceBaseline.product_baseline_ready)}</p>
        </div>
      </header>

      <section className="context-card" data-administration-workspace-section="data-scope">
        <div className="context-card-header">
          <div>
            <strong><LocalizedText id="copy.operational_data_scope_c8bb14b7" /></strong>
            <p><LocalizedText id="copy.validation_and_legacy_unscoped_records_are_hidden_by_7ba8d38d" /></p>
          </div>
          {dataScope.scope_type === 'platform' ? (
            <label className="filter-toggle">
              <input
                checked={includeValidation}
                onChange={(event) => setIncludeValidation(event.target.checked)}
                type="checkbox"
              />
              <LocalizedText id="copy.include_validation_data_8cf591c4" /></label>
          ) : <span><LocalizedText id="copy.organization_scoped_eb91a8c8" /></span>}
        </div>
      </section>

      <section className="grid" data-administration-workspace-section="administration-summary">
        <CountCard label={t('copy.organizations_07605242')} value={organizationCounts.organizations} />
        <CountCard label={t('copy.installed_capabilities_be373bb4')} value={installedCapabilities.length} />
        <CountCard label={t('copy.configured_capabilities_c700fe5b')} value={Object.values(configuredCapabilities).filter(Boolean).length} />
        <CountCard label={t('copy.roles_47dcc27d')} value={securityTotals.roles} />
        <CountCard label={t('copy.permissions_d06d5557')} value={securityTotals.permissions} />
        <CountCard label={t('copy.reference_tenant_a04947d9')} value={referenceReadiness.reference_tenant_ready} ready={Boolean(referenceReadiness.reference_tenant_ready)} />
      </section>

      <section className="table-card" data-administration-workspace-section="capabilities">
        <h2><LocalizedText id="copy.platform_capabilities_15ba63db" /></h2>
        <div className="metrics-grid">
          {Object.entries(configuredCapabilities).map(([key, value]) => (
            <article className="metric-card" key={key}>
              <small>{key.replaceAll('_', ' ')}</small>
              <strong>{asText(value)}</strong>
            </article>
          ))}
        </div>
        <p className="muted-text"><LocalizedText id="copy.installed_dedd8ab8" />{installedCapabilities.join(', ') || 'No installed capabilities reported'}</p>
      </section>

      <section className="table-card" data-administration-workspace-section="organizations">
        <h2><LocalizedText id="copy.organizations_07605242" /></h2>
        <div className="metrics-grid">
          <article className="metric-card"><small><LocalizedText id="copy.organization_count_98b55bf5" /></small><strong>{asText(organizationCounts.organizations, '0')}</strong></article>
          <article className="metric-card"><small><LocalizedText id="copy.root_nodes_5c4147ed" /></small><strong>{rootNodes.length}</strong></article>
          <article className="metric-card"><small><LocalizedText id="copy.hierarchy_nodes_a5d2666d" /></small><strong>{nodes.length}</strong></article>
          <article className="metric-card"><small><LocalizedText id="copy.relationships_229981dd" /></small><strong>{relationships.length}</strong></article>
        </div>
      </section>
      <SimpleTable title={t('copy.organization_list_0f64eb0d')} rows={asList(organizations.organizations)} columns={['slug', 'name', 'status']} />
      <SimpleTable title={t('copy.root_nodes_e97b0cf8')} rows={rootNodes} columns={['code', 'name', 'node_type', 'status']} />

      <section className="table-card" data-administration-workspace-section="security">
        <h2><LocalizedText id="copy.security_f25ce1b8" /></h2>
        <div className="metrics-grid">
          {['roles', 'permissions', 'policies', 'assignments', 'role_permissions'].map((key) => (
            <article className="metric-card" key={key}>
              <small>{key.replaceAll('_', ' ')}</small>
              <strong>{asText(securityTotals[key], '0')}</strong>
            </article>
          ))}
        </div>
      </section>
      <SimpleTable title={t('copy.roles_47dcc27d')} rows={roles} columns={['name', 'status']} />
      <SimpleTable title={t('copy.permissions_d06d5557')} rows={asList(security.permissions)} columns={['code', 'name', 'status', 'scope_domain']} />
      <SimpleTable title={t('copy.policies_8d611849')} rows={asList(security.policies)} columns={['name', 'status']} />
      <SimpleTable title={t('copy.role_assignments_1baf0a07')} rows={assignments} columns={['principal', 'role', 'status']} />

      <section className="table-card" data-administration-workspace-section="documents">
        <h2><LocalizedText id="copy.document_configuration_3482cd36" /></h2>
        <div className="metrics-grid">
          <article className="metric-card"><small><LocalizedText id="copy.document_types_08bf66a2" /></small><strong>{asList(documents.document_types).length}</strong></article>
          <article className="metric-card"><small><LocalizedText id="copy.metadata_templates_0579ab7b" /></small><strong>{asList(documents.metadata_templates).length}</strong></article>
          <article className="metric-card"><small><LocalizedText id="copy.retention_policies_62b9cc1e" /></small><strong>{asList(documents.retention_policies).length}</strong></article>
          <article className="metric-card"><small><LocalizedText id="copy.classification_rules_46a532c5" /></small><strong>{asList(documents.classification_rules).length}</strong></article>
          <article className="metric-card"><small><LocalizedText id="copy.collections_4bbb632f" /></small><strong>{asList(documents.collections).length}</strong></article>
        </div>
      </section>
      <SimpleTable title={t('copy.document_types_b3c8a1c8')} rows={asList(documents.document_types)} columns={['code', 'name', 'version', 'status']} />
      <SimpleTable title={t('copy.metadata_templates_83abce10')} rows={asList(documents.metadata_templates)} columns={['code', 'name', 'status']} />
      <SimpleTable title={t('copy.retention_policies_67398ca1')} rows={asList(documents.retention_policies)} columns={['code', 'name', 'status']} />
      <SimpleTable title={t('copy.classification_rules_f6c29eb4')} rows={asList(documents.classification_rules)} columns={['code', 'name', 'status']} />

      <section className="table-card" data-administration-workspace-section="knowledge">
        <h2><LocalizedText id="copy.knowledge_configuration_ad67a2e2" /></h2>
        <div className="metrics-grid">
          <article className="metric-card"><small><LocalizedText id="copy.collections_4bbb632f" /></small><strong>{asList(knowledge.collections).length}</strong></article>
          <article className="metric-card"><small><LocalizedText id="copy.knowledge_sources_516cf9f9" /></small><strong>{asList(documents.knowledge_sources).length}</strong></article>
          <article className="metric-card"><small><LocalizedText id="copy.knowledge_documents_e25dbfc5" /></small><strong>{asText(asMap(knowledge.knowledge_documents).count, '0')}</strong></article>
          <article className="metric-card"><small><LocalizedText id="copy.knowledge_chunks_99e06082" /></small><strong>{asText(asMap(knowledge.knowledge_chunks).count, '0')}</strong></article>
        </div>
      </section>
      <SimpleTable title={t('copy.collections_4bbb632f')} rows={asList(knowledge.collections)} columns={['code', 'name', 'status']} />
      <SimpleTable title={t('copy.knowledge_sources_a70fa55f')} rows={asList(documents.knowledge_sources)} columns={['source_type', 'status']} />

      <section className="table-card" data-administration-workspace-section="assistants">
        <h2><LocalizedText id="pages.ai.title" /></h2>
        <div className="metrics-grid">
          <article className="metric-card"><small><LocalizedText id="copy.assistants_127c1ab3" /></small><strong>{asList(assistants.assistant_definitions).length}</strong></article>
          <article className="metric-card"><small><LocalizedText id="copy.models_f3798f81" /></small><strong>{asList(assistants.models).length}</strong></article>
          <article className="metric-card"><small><LocalizedText id="copy.prompts_eea5311d" /></small><strong>{asList(assistants.prompts).length}</strong></article>
          <article className="metric-card"><small><LocalizedText id="copy.guardrails_2dd5f894" /></small><strong>{asList(assistants.guardrails).length}</strong></article>
          <article className="metric-card"><small><LocalizedText id="copy.workflows_825ce9e9" /></small><strong>{asList(assistants.workflows).length}</strong></article>
        </div>
      </section>
      <SimpleTable title={t('copy.assistant_definitions_fada08a2')} rows={asList(assistants.assistant_definitions)} columns={['assistant_key', 'assistant_name', 'assistant_status', 'assistant_version']} />
      <SimpleTable title={t('copy.models_f3798f81')} rows={asList(assistants.models)} columns={['code', 'name', 'status', 'enabled']} />
      <SimpleTable title={t('copy.prompts_eea5311d')} rows={asList(assistants.prompts)} columns={['code', 'name', 'version', 'status']} />
      <SimpleTable title={t('copy.guardrails_2dd5f894')} rows={asList(assistants.guardrails)} columns={['code', 'name', 'guardrail_type', 'status']} />
      <SimpleTable title={t('copy.workflows_825ce9e9')} rows={asList(assistants.workflows)} columns={['code', 'name', 'status']} />

      <section className="table-card" data-administration-workspace-section="reference-tenant">
        <h2><LocalizedText id="copy.reference_tenant_639d1ca4" /></h2>
        <div className="metrics-grid">
          <article className="metric-card"><small><LocalizedText id="copy.readiness_6dc1222c" /></small><strong>{asText(referenceReadiness.reference_tenant_ready)}</strong></article>
          <article className="metric-card"><small><LocalizedText id="copy.product_baseline_3abe13d4" /></small><strong>{asText(referenceBaseline.product_baseline_ready)}</strong></article>
          <article className="metric-card"><small><LocalizedText id="copy.pending_capabilities_84fd1f5a" /></small><strong>{asList(referenceBaseline.pending_capabilities).length}</strong></article>
          <article className="metric-card"><small><LocalizedText id="copy.blocking_issues_c74144eb" /></small><strong>{asList(referenceBaseline.blocking_issues).length}</strong></article>
        </div>
      </section>

      <section className="table-card" data-administration-workspace-section="diagnostics">
        <h2><LocalizedText id="copy.diagnostics_3af2279f" /></h2>
        <div className="alerts-grid">
          {[
            ['Blocking issues', diagnostics.blockingIssues],
            ['Warnings', diagnostics.warnings],
            ['Pending capabilities', diagnostics.pendingCapabilities],
            ['Degraded domains', diagnostics.degradedDomains],
          ].map(([title, values]) => (
            <article className="context-card" key={title as string}>
              <div className="context-card-header">
                <strong>{title as string}</strong>
                <span>{(values as Array<Row | string>).length}</span>
              </div>
              {(values as Array<Row | string>).length > 0 ? (
                <ul className="compact-list">
                  {(values as Array<Row | string>).map((item, index) => (
                    <li key={`${title}-${index}`}>{typeof item === 'string' ? item : issueText(item, t)}</li>
                  ))}
                </ul>
              ) : (
                <p><LocalizedText id="common.noItems" /></p>
              )}
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
