'use client';

import { useI18n } from '../../i18n/I18nProvider';

import { LocalizedText } from '../layout/LocalizedText';

import { useEffect, useState } from 'react';

import {
  getEnterpriseApiIntegrationRuntime,
  type EnterpriseApiIntegrationRuntime,
} from '../../lib/enterprise-api-integration-api';
import { localizedProductLabel } from '../../lib/presentation';

function asText(value: unknown, fallback = '-'): string {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return String(value);
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

function MetricCard({ label, value }: { label: string; value: unknown }) {
  const { t } = useI18n();
  return (
    <article className="metric-card">
      <small>{label}</small>
      <strong>{localizedProductLabel(value, t, '0')}</strong>
    </article>
  );
}

function Summary({ runtime }: { runtime: EnterpriseApiIntegrationRuntime }) {
  const { t } = useI18n();
  const summary = runtime.workspace_summary ?? {};
  const readiness = runtime.api_readiness ?? {};
  return (
    <section className="grid" data-api-integration-section="summary">
      <article className="card health-card">
        <div className="context-card-header">
          <h2><LocalizedText id="copy.api_integration_5d67ec88" /></h2>
          <span className={statusClass(Boolean(summary.api_center_ready))}></span>
        </div>
        <span className="metric-value">{localizedProductLabel(runtime.runtime_status, t)}</span>
      </article>
      <MetricCard label={t('copy.endpoints_b71c5271')} value={summary.endpoint_count} />
      <MetricCard label={t('copy.runtime_endpoints_2eb4b40f')} value={summary.runtime_endpoint_count} />
      <MetricCard label={t('dynamic.connectors')} value={summary.connector_count} />
      <MetricCard label={t('copy.overall_api_score_41cb5eed')} value={readiness.overall_api_score} />
      <MetricCard label={t('copy.security_score_279d49fa')} value={readiness.security_score} />
      <MetricCard label={t('copy.integration_score_4c32e70c')} value={readiness.integration_score} />
      <MetricCard label={t('copy.postgresql_source_33bab8bf')} value={summary.postgresql_source_of_truth} />
    </section>
  );
}

function ApiInventory({ runtime }: { runtime: EnterpriseApiIntegrationRuntime }) {
  const { t } = useI18n();
  const inventory = runtime.platform_api_inventory ?? {};
  const groups = runtime.api_groups ?? {};
  return (
    <section className="table-card" data-api-integration-section="api-inventory">
      <h2><LocalizedText id="copy.platform_api_inventory_98b52962" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.endpoint_count_f3ae7c69')} value={inventory.endpoint_count} />
        <MetricCard label={t('copy.runtime_endpoints_2eb4b40f')} value={inventory.runtime_endpoint_count} />
        <MetricCard label={t('copy.openapi_acb3d9a7')} value={inventory.openapi_available} />
        <MetricCard label={t('copy.health_endpoints_b7330826')} value={inventory.health_endpoints} />
        <MetricCard label={t('copy.public_apis_2735f751')} value={groups.public_apis} />
        <MetricCard label={t('copy.private_apis_67e56f65')} value={groups.private_apis} />
        <MetricCard label={t('copy.internal_apis_65841f6a')} value={groups.internal_apis} />
        <MetricCard label={t('copy.deprecated_apis_600c4c32')} value={groups.deprecated_apis} />
      </div>
    </section>
  );
}

function EndpointCatalog({ runtime }: { runtime: EnterpriseApiIntegrationRuntime }) {
  const { t } = useI18n();
  return (
    <section className="table-card" data-api-integration-section="endpoint-catalog">
      <h2><LocalizedText id="copy.endpoint_catalog_e8c1c598" /></h2>
      <table>
        <thead>
          <tr><th><LocalizedText id="copy.path_519e3913" /></th><th><LocalizedText id="copy.methods_7e4ac680" /></th><th><LocalizedText id="copy.group_171a0606" /></th><th><LocalizedText id="copy.visibility_7d9ff4f0" /></th><th><LocalizedText id="copy.runtime_c4740e4c" /></th></tr>
        </thead>
        <tbody>
          {runtime.endpoint_catalog.slice(0, 30).map((endpoint) => (
            <tr key={`${asText(endpoint.path)}-${asText(endpoint.methods)}`}>
              <td><small>{asText(endpoint.path)}</small></td>
              <td>{Array.isArray(endpoint.methods) ? endpoint.methods.join(', ') : '-'}</td>
              <td>{asText(endpoint.api_group)}</td>
              <td>{asText(endpoint.visibility)}</td>
              <td>{localizedProductLabel(endpoint.runtime_endpoint, t)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function SecurityIntegration({ runtime }: { runtime: EnterpriseApiIntegrationRuntime }) {
  const { t } = useI18n();
  const auth = runtime.authentication_methods ?? {};
  const authorization = runtime.authorization_model ?? {};
  const scopes = runtime.security_scopes ?? {};
  const jwt = runtime.jwt_readiness ?? {};
  return (
    <section className="table-card" data-api-integration-section="security">
      <h2><LocalizedText id="copy.security_and_authorization_152db502" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.identity_ready_4ee7ee2f')} value={auth.identity_ready} />
        <MetricCard label={t('copy.authorization_ready_ffd746ae')} value={authorization.authorization_ready} />
        <MetricCard label={t('copy.effective_permissions_17c0fe8a')} value={authorization.effective_permissions_ready} />
        <MetricCard label={t('copy.scope_count_64de98f7')} value={scopes.scope_count} />
        <MetricCard label={t('copy.jwt_ready_064bb873')} value={jwt.jwt_ready} />
        <MetricCard label={t('copy.secrets_exposed_52f29847')} value={jwt.secrets_exposed} />
      </div>
    </section>
  );
}

function IntegrationInventory({ runtime }: { runtime: EnterpriseApiIntegrationRuntime }) {
  const { t } = useI18n();
  const connectors = runtime.connector_integrations ?? {};
  const external = runtime.external_integrations ?? {};
  const webhooks = runtime.webhook_inventory ?? {};
  const events = runtime.event_catalog ?? {};
  return (
    <section className="table-card" data-api-integration-section="integrations">
      <h2><LocalizedText id="copy.integration_governance_9e4e2fd9" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.connector_count_77521525')} value={connectors.connector_count} />
        <MetricCard label={t('copy.configured_connectors_54b8a9ae')} value={connectors.configured_connectors} />
        <MetricCard label={t('copy.synchronization_ready_3b842f85')} value={connectors.synchronization_ready} />
        <MetricCard label={t('copy.provider_count_d634c2f3')} value={external.provider_count} />
        <MetricCard label={t('copy.webhook_count_71e258e8')} value={webhooks.webhook_count} />
        <MetricCard label={t('copy.audit_events_9e7d8c07')} value={events.audit_event_count} />
        <MetricCard label={t('copy.provider_calls_d9cbf2c7')} value={external.provider_calls_performed} />
        <MetricCard label={t('copy.webhook_execution_25088aed')} value={webhooks.webhook_execution_performed} />
      </div>
    </section>
  );
}

function IntegrationOverview({ runtime }: { runtime: EnterpriseApiIntegrationRuntime }) {
  const { date } = useI18n();
  const connectors = runtime.connector_integrations ?? {};
  const connectorItems = asList(connectors.connectors);
  const connectorTypes = asList(connectors.connector_types);
  const configured = Number(connectors.configured_connectors ?? 0);
  return (
    <section className="table-card" data-api-integration-section="overview">
      <div className="section-header">
        <div><span className="eyebrow"><LocalizedText id="copy.connected_systems_30ef8fbb" /></span><h2><LocalizedText id="pages.integrations.title" /></h2><p><LocalizedText id="copy.connectors_bring_governed_content_and_activity_into__afe458a1" /></p></div>
      </div>
      {configured > 0 ? (
        <><div className="report-domain-grid">
          <article><h3><LocalizedText id="copy.configured_connectors_54b8a9ae" /></h3><strong>{configured}</strong><p>{Boolean(connectors.synchronization_ready) ? <LocalizedText id="copy.synchronization_is_ready_d3635b26" /> : <LocalizedText id="copy.synchronization_needs_attention_e1f2a432" />}</p></article>
          <article><h3><LocalizedText id="copy.available_connectors_91efbd90" /></h3><strong>{asText(connectors.connector_count, '0')}</strong><p><LocalizedText id="copy.managed_by_the_persisted_connector_runtime_01a3995c" /></p></article>
        </div><table><thead><tr><th><LocalizedText id="copy.integration_899e5920" /></th><th><LocalizedText id="common.type" /></th><th><LocalizedText id="common.status" /></th><th><LocalizedText id="copy.last_activity_1c73b806" /></th></tr></thead><tbody>{connectorItems.map((connector) => <tr key={asText(connector.connector_id)}><td>{asText(connector.name)}</td><td>{asText(connectorTypes.find((item) => String(item.connector_type_id) === String(connector.connector_type_id))?.name, 'Connector')}</td><td>{connector.configuration_status === 'configured' ? <LocalizedText id="status.configured" /> : <LocalizedText id="copy.needs_setup_522ebae4" />}</td><td>{connector.last_run_at ? date(String(connector.last_run_at), { dateStyle: 'medium', timeStyle: 'short' }) : <LocalizedText id="copy.no_synchronization_yet_81bf0431" />}</td></tr>)}</tbody></table></>
      ) : (
        <div className="empty-state"><strong><LocalizedText id="copy.no_connectors_configured_e5a95b5e" /></strong><p><LocalizedText id="copy.the_platform_api_catalog_is_available_below_for_auth_f42131cb" /></p></div>
      )}
    </section>
  );
}

function Diagnostics({ runtime }: { runtime: EnterpriseApiIntegrationRuntime }) {
  const { t } = useI18n();
  const diagnostics = runtime.integration_diagnostics ?? {};
  const reference = runtime.reference_tenant_integration_readiness ?? {};
  const groups = [
    ['Warnings', runtime.warnings],
    ['Recommendations', runtime.operational_recommendations],
    ['Pending integrations', asList(diagnostics.pending_integrations)],
    ['Blocking issues', asList(diagnostics.blocking_issues)],
  ];
  return (
    <section className="table-card" data-api-integration-section="diagnostics">
      <h2><LocalizedText id="copy.diagnostics_and_reference_tenant_a23dfd61" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.reference_ready_b2db7c15')} value={reference.reference_tenant_ready} />
        <MetricCard label={t('copy.reference_integration_0b585c67')} value={reference.integration_ready} />
        <MetricCard label={t('copy.side_effects_f9b9f592')} value={runtime.side_effects_performed} />
        <MetricCard label={t('copy.external_calls_2326bb0c')} value={runtime.external_calls_performed} />
        <MetricCard label={t('copy.llm_used_2f2d3965')} value={runtime.llm_used} />
        <MetricCard label={t('copy.qdrant_used_71ab4e52')} value={runtime.qdrant_used} />
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

export function EnterpriseApiIntegrationCenter() {
  const { t } = useI18n();
  const [runtime, setRuntime] = useState<EnterpriseApiIntegrationRuntime | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const payload = await getEnterpriseApiIntegrationRuntime();
        if (!cancelled) setRuntime(payload);
      } catch (loadError) {
        if (!cancelled) {
          setError(
            loadError instanceof Error
              ? loadError.message
              : t('feedback.integrationsUnavailable'),
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [reloadToken, t]);

  if (loading && !runtime) {
    return (
      <section className="card" data-api-integration-section="loading">
        <h2><LocalizedText id="copy.loading_integrations_a9c4c289" /></h2>
        <p><LocalizedText id="copy.retrieving_connections_and_integration_status_b3e300b2" /></p>
      </section>
    );
  }

  if (error || !runtime) {
    return (
      <section className="card" data-api-integration-section="error">
        <h2><LocalizedText id="copy.integrations_unavailable_2186758e" /></h2>
        <p>{error ?? <LocalizedText id="copy.no_integration_status_was_returned_a2f892a5" />}</p>
        <button className="button secondary" type="button" onClick={() => setReloadToken((value) => value + 1)}><LocalizedText id="common.actions.retry" /></button>
      </section>
    );
  }

  return (
    <div className="product-workspace">
      {loading ? <p className="context-message"><LocalizedText id="copy.refreshing_integration_status_ba0d6fb1" /></p> : null}
      <IntegrationOverview runtime={runtime} />
      <details className="advanced-panel"><summary><LocalizedText id="copy.api_catalog_and_advanced_integration_details_d5a8ec7c" /></summary><div className="advanced-panel-content">
        <Summary runtime={runtime} />
        <IntegrationInventory runtime={runtime} />
        <ApiInventory runtime={runtime} />
        <EndpointCatalog runtime={runtime} />
        <SecurityIntegration runtime={runtime} />
        <Diagnostics runtime={runtime} />
      </div></details>
    </div>
  );
}
