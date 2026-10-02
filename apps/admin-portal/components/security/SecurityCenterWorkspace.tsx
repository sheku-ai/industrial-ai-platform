'use client';

import { useI18n } from '../../i18n/I18nProvider';

import { LocalizedText } from '../layout/LocalizedText';

import { useEffect, useState } from 'react';

import {
  getSecurityCenterRuntime,
  type SecurityCenterRuntime,
} from '../../lib/security-center-api';
import { localizedApiError, localizedProductLabel, productLabel } from '../../lib/presentation';
import { useOrganization } from '../organization/OrganizationContext';
import { GlobalSecurityAdministration } from './GlobalSecurityAdministration';
import { OrganizationAccessManager } from './OrganizationAccessManager';

function asText(value: unknown, fallback = '-'): string {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'boolean') return String(value);
  if (typeof value === 'string' && /^[a-z0-9]+(?:_[a-z0-9]+)+$/.test(value)) return productLabel(value, fallback);
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

const SECURITY_ITEM_KEYS: Record<string, string> = {
  assign_roles_to_principals: 'securitySurface.items.assignRoles',
  assignments_not_configured: 'securitySurface.items.assignmentsNotConfigured',
  configure_permissions: 'securitySurface.items.configurePermissions',
  configure_roles: 'securitySurface.items.configureRoles',
  external_identity_provider_not_configured: 'securitySurface.items.externalIdentityProviderOptional',
  jwt_runtime_not_required_for_center: 'securitySurface.items.jwtNotRequired',
  permissions_not_configured: 'securitySurface.items.permissionsNotConfigured',
  review_effective_permissions: 'securitySurface.items.reviewEffectivePermissions',
  roles_not_configured: 'securitySurface.items.rolesNotConfigured',
};

const SECURITY_GATE_KEYS: Record<string, string> = {
  audit_runtime_available: 'securitySurface.gates.auditRuntime',
  cors_restricted: 'securitySurface.gates.corsRestricted',
  cross_organization_access_blocked: 'securitySurface.gates.organizationIsolation',
  debug_disabled: 'securitySurface.gates.debugDisabled',
  production_authentication_required: 'securitySurface.gates.authentication',
  production_configuration_fail_closed: 'securitySurface.gates.failClosed',
  provider_execution_explicit: 'securitySurface.gates.providerExecution',
  secret_placeholders_absent: 'securitySurface.gates.secretPlaceholders',
  security_findings_clear: 'securitySurface.gates.findingsClear',
};

const SECURITY_SETTING_KEYS: Record<string, string> = {
  ai_optional: 'securitySurface.settings.aiOptional',
  authentication_cookie_secure: 'securitySurface.settings.secureCookie',
  authentication_enforced: 'securitySurface.settings.authentication',
  cors_restricted: 'securitySurface.settings.cors',
  database_url: 'securitySurface.settings.database',
  debug_disabled: 'securitySurface.settings.debug',
  feature_embeddings_enabled: 'securitySurface.settings.embeddings',
  feature_vector_retrieval_enabled: 'securitySurface.settings.vectorRetrieval',
  identity_database_configuration_present: 'securitySurface.settings.identityDatabase',
  object_storage_bucket_present: 'securitySurface.settings.objectStorageBucket',
  object_storage_transport_secure: 'securitySurface.settings.objectStorageTransport',
  object_storage_url_production_safe: 'securitySurface.settings.objectStorageUrl',
  provider_execution_explicit: 'securitySurface.settings.providerExecution',
  secret_store_provider: 'securitySurface.settings.secretStore',
};

function securityLabel(value: unknown, keys: Record<string, string>, translate: (key: string) => string): string {
  const code = String(value ?? '').trim().toLowerCase();
  return keys[code] ? translate(keys[code]) : translate('dynamic.detailsAvailable');
}

function issueText(item: Record<string, unknown>, translate: (key: string) => string): string {
  return securityLabel(item.code, SECURITY_ITEM_KEYS, translate);
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

function Summary({ runtime }: { runtime: SecurityCenterRuntime }) {
  const { t } = useI18n();
  const summary = runtime.workspace_summary ?? {};
  return (
    <section className="grid" data-security-center-section="summary">
      <article className="card health-card">
        <div className="context-card-header">
          <h2><LocalizedText id="copy.security_ready_96fddb06" /></h2>
          <span className={statusClass(Boolean(summary.security_ready))}></span>
        </div>
        <span className="metric-value">{localizedProductLabel(summary.security_ready, t)}</span>
      </article>
      <MetricCard label={t('copy.roles_47dcc27d')} value={summary.roles_ready} />
      <MetricCard label={t('copy.permissions_d06d5557')} value={summary.permissions_ready} />
      <MetricCard label={t('copy.policies_8d611849')} value={summary.policies_ready} />
      <MetricCard label={t('copy.assignments_057d58c7')} value={summary.assignments_ready} />
      <MetricCard label={t('copy.effective_permissions_17c0fe8a')} value={summary.effective_permissions_ready} />
      <MetricCard label={t('copy.audit_traceability_c6a5757b')} value={summary.audit_traceability_ready} />
      <MetricCard label={t('copy.postgresql_source_33bab8bf')} value={summary.postgresql_source_of_truth} />
    </section>
  );
}

function SecurityAcceptance({ runtime }: { runtime: SecurityCenterRuntime }) {
  const { t } = useI18n();
  const acceptance = asRecord(runtime.security_acceptance);
  const gates = asList(acceptance.gates);
  const findings = asList(runtime.security_findings);
  const policies = asList(runtime.security_policies);
  const checks = asList(acceptance.configuration_checks);
  return (
    <section className="table-card" data-security-center-section="security-acceptance">
      <h2><LocalizedText id="copy.security_acceptance_803054f8" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.readiness_6dc1222c')} value={acceptance.status} />
        <MetricCard label={t('copy.security_ready_96fddb06')} value={acceptance.security_ready} />
        <MetricCard label={t('copy.policies_8d611849')} value={policies.length} />
        <MetricCard label={t('copy.findings_ca9b7e7e')} value={findings.length} />
        <MetricCard label={t('copy.configuration_checks_30d3dfba')} value={checks.length} />
      </div>
      <table>
        <thead>
          <tr><th><LocalizedText id="copy.gate_5701b5f6" /></th><th><LocalizedText id="common.status" /></th><th><LocalizedText id="copy.evidence_7ea014de" /></th><th><LocalizedText id="copy.summary_12b71c3e" /></th></tr>
        </thead>
        <tbody>
          {gates.map((gate) => (
            <tr key={asText(gate.gate_code)}>
              <td>{securityLabel(gate.gate_code, SECURITY_GATE_KEYS, t)}<small className="table-secondary"><code>{asText(gate.gate_code)}</code></small></td>
              <td>{localizedProductLabel(gate.status, t)}</td>
              <td>{localizedProductLabel(gate.evidence_type, t)}</td>
              <td>{t(gate.status === 'passed' ? 'securitySurface.gatePassedHelp' : 'securitySurface.gateAttentionHelp')}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="alerts-grid">
        <article className="context-card">
          <div className="context-card-header">
            <strong><LocalizedText id="copy.open_findings_ded0d64a" /></strong>
            <span>{findings.length}</span>
          </div>
          {findings.length > 0 ? (
            <ul className="compact-list">
              {findings.slice(0, 8).map((finding) => (
                <li key={asText(finding.id)}>
                  {localizedProductLabel(finding.severity, t)} · {t('securitySurface.findingRequiresReview')} {finding.rule ? <code>{asText(finding.rule)}</code> : null}
                </li>
              ))}
            </ul>
          ) : (
            <p><LocalizedText id="copy.no_security_findings_reported_ab63fbb6" /></p>
          )}
        </article>
        <article className="context-card">
          <div className="context-card-header">
            <strong><LocalizedText id="copy.configuration_checks_30d3dfba" /></strong>
            <span>{checks.length}</span>
          </div>
          {checks.length > 0 ? (
            <ul className="compact-list">
              {checks.slice(0, 8).map((check) => (
                <li key={asText(check.setting_code)}>
                  {securityLabel(check.setting_code, SECURITY_SETTING_KEYS, t)}: {localizedProductLabel(check.status, t)} <small className="table-secondary"><code>{asText(check.setting_code)}</code></small>
                </li>
              ))}
            </ul>
          ) : (
            <p><LocalizedText id="copy.no_configuration_checks_reported_278d247b" /></p>
          )}
        </article>
      </div>
    </section>
  );
}

function Diagnostics({ runtime }: { runtime: SecurityCenterRuntime }) {
  const { t } = useI18n();
  const groups = [
    ['securitySurface.diagnostics.warnings', runtime.warnings],
    ['securitySurface.diagnostics.recommendations', runtime.recommendations],
    ['securitySurface.diagnostics.pending', runtime.pending_capabilities],
    ['securitySurface.diagnostics.audit', asList(asRecord(runtime.security_audit).recent_events)],
  ];
  return (
    <section className="table-card" data-security-center-section="diagnostics">
      <h2><LocalizedText id="copy.access_diagnostics_and_audit_traceability_44496106" /></h2>
      <div className="metrics-grid">
        <MetricCard label={t('copy.reference_security_568b0cc6')} value={asRecord(runtime.reference_tenant_security).security_ready} />
        <MetricCard label={t('copy.audit_events_9e7d8c07')} value={asRecord(runtime.security_audit).audit_event_count} />
        <MetricCard label={t('copy.unattached_permissions_68776150')} value={asRecord(runtime.access_diagnostics).unattached_permissions} />
        <MetricCard label={t('copy.side_effects_f9b9f592')} value={runtime.side_effects_performed} />
      </div>
      <div className="alerts-grid">
        {groups.map(([label, values]) => (
          <article className="context-card" key={label as string}>
            <div className="context-card-header">
              <strong>{t(label as string)}</strong>
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

export function SecurityCenterWorkspace() {
  const { t } = useI18n();
  const { organization } = useOrganization();
  const [runtime, setRuntime] = useState<SecurityCenterRuntime | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      if (!organization) {
        setRuntime(null);
        setError(null);
        setLoading(false);
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const payload = await getSecurityCenterRuntime();
        if (!cancelled) setRuntime(payload);
      } catch (loadError) {
        if (!cancelled) {
          setError(localizedApiError(loadError, t, 'feedback.securityRuntimeUnavailable'));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [organization, reloadToken, t]);

  if (!organization) {
    return (
      <div className="product-workspace" data-security-center="platform-only">
        <GlobalSecurityAdministration />
        <section className="card">
          <h2>{t('shell.noOrganizationAvailable')}</h2>
          <p>{t('shell.requestOrganizationHelp')}</p>
        </section>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="product-workspace">
        <GlobalSecurityAdministration />
        <section className="card" data-security-center-section="loading">
          <h2><LocalizedText id="copy.loading_security_center_d81e36ee" /></h2>
          <p><LocalizedText id="copy.retrieving_security_posture_from_postgresql_backed_r_ad98b1ac" /></p>
        </section>
      </div>
    );
  }

  if (error || !runtime) {
    return (
      <div className="product-workspace">
        <GlobalSecurityAdministration />
        <section className="card" data-security-center-section="error">
          <h2><LocalizedText id="copy.security_center_unavailable_d0a273b6" /></h2>
          <p>{error ?? <LocalizedText id="copy.no_security_center_runtime_payload_was_returned_f8954ce1" />}</p>
          <button className="button secondary" type="button" onClick={() => setReloadToken((value) => value + 1)}><LocalizedText id="common.actions.retry" /></button>
        </section>
      </div>
    );
  }

  return (
    <div className="product-workspace" data-security-center="ready">
      <GlobalSecurityAdministration />
      <OrganizationAccessManager />
      <details className="advanced-panel"><summary><LocalizedText id="copy.advanced_security_diagnostics_and_service_identities_8017e34e" /></summary><div className="advanced-panel-content"><Summary runtime={runtime} /><section className="table-card"><h2><LocalizedText id="copy.technical_identities_and_validation_records_e5521cba" /></h2><div className="metrics-grid"><MetricCard label={t('copy.validation_roles_1261c3b6')} value={asList(asRecord(runtime.advanced_security_records).validation_roles).length} /><MetricCard label={t('copy.service_assignments_34cb8551')} value={asList(asRecord(runtime.advanced_security_records).service_assignments).length} /><MetricCard label={t('copy.technical_permissions_3fd24fc1')} value={asList(asRecord(runtime.advanced_security_records).technical_permissions).length} /></div><p><LocalizedText id="copy.these_persisted_records_are_excluded_from_the_operat_ff3a0b55" /></p></section><SecurityAcceptance runtime={runtime} /><Diagnostics runtime={runtime} /></div></details>
    </div>
  );
}
