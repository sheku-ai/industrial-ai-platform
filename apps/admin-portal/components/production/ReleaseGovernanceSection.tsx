'use client';

import { localizedProductLabel } from '../../lib/presentation';

import { useI18n } from '../../i18n/I18nProvider';

import { LocalizedText } from '../layout/LocalizedText';

import { useEffect, useState } from 'react';

import {
  completeGovernedBuild,
  createGovernedBuild,
  createGovernedRelease,
  evaluateGovernedRelease,
  getLatestReleaseReadiness,
  listGovernedReleases,
  registerGovernedArtifact,
  registerGovernedBuildManifest,
  registerGovernedDeploymentManifest,
  registerReleaseCompatibility,
  registerReleaseMigration,
  registerReleaseRollback,
  verifyGovernedArtifact,
  type GovernedArtifact,
  type GovernedBuild,
  type GovernedRelease,
  type ReleaseReadiness,
} from '../../lib/production-readiness-api';

function text(value: unknown, fallback = 'Not available'): string {
  return value === null || value === undefined || value === '' ? fallback : String(value);
}

function list(value: string): string[] {
  return value.split(',').map((item) => item.trim()).filter(Boolean);
}

function issue(value: Record<string, unknown>): string {
  return text(value.message ?? value.code ?? value.reason);
}

function Field({ label, value, onChange, type = 'text' }: {
  label: string; value: string; onChange: (value: string) => void; type?: string;
}) {
  return <label>{label}<input type={type} value={value} onChange={(event) => onChange(event.target.value)} /></label>;
}

export function ReleaseGovernanceSection() {
  const { t } = useI18n();
  const [readiness, setReadiness] = useState<ReleaseReadiness | null>(null);
  const [releases, setReleases] = useState<GovernedRelease[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [releaseCode, setReleaseCode] = useState('');
  const [version, setVersion] = useState('');
  const [edition, setEdition] = useState<'community' | 'enterprise'>('community');
  const [channel, setChannel] = useState('release_candidate');
  const [sourceRepository, setSourceRepository] = useState('sheku-ai/industrial-ai-platform');
  const [sourceRevision, setSourceRevision] = useState('');
  const [buildNumber, setBuildNumber] = useState('');
  const [buildTimestamp, setBuildTimestamp] = useState('');
  const [targetPlatform, setTargetPlatform] = useState('container');
  const [targetArchitecture, setTargetArchitecture] = useState('multi_arch');
  const [configurationProfile, setConfigurationProfile] = useState('production');
  const [schemaRevision, setSchemaRevision] = useState('');
  const [pythonVersion, setPythonVersion] = useState('');
  const [nodeVersion, setNodeVersion] = useState('');
  const [requiredArtifactCodes, setRequiredArtifactCodes] = useState('api-image,portal-image,migration-bundle');
  const [artifactCode, setArtifactCode] = useState('');
  const [artifactType, setArtifactType] = useState('container_image');
  const [artifactComponent, setArtifactComponent] = useState('api');
  const [artifactReference, setArtifactReference] = useState('');
  const [checksum, setChecksum] = useState('');
  const [digest, setDigest] = useState('');
  const [compatibilityType, setCompatibilityType] = useState('database_schema');
  const [minimumVersion, setMinimumVersion] = useState('');
  const [maximumVersion, setMaximumVersion] = useState('');
  const [compatibilityEvidence, setCompatibilityEvidence] = useState('');
  const [migrationFrom, setMigrationFrom] = useState('');
  const [migrationTo, setMigrationTo] = useState('');
  const [migrationStrategy, setMigrationStrategy] = useState('forward_only');
  const [migrationEvidence, setMigrationEvidence] = useState('');
  const [rollbackTarget, setRollbackTarget] = useState('');
  const [rollbackEvidence, setRollbackEvidence] = useState('');

  async function refresh() {
    const [response, inventory] = await Promise.all([getLatestReleaseReadiness(), listGovernedReleases()]);
    setReadiness(response.readiness ?? null);
    setReleases(inventory);
  }

  useEffect(() => {
    let cancelled = false;
    Promise.all([getLatestReleaseReadiness(), listGovernedReleases()])
      .then(([response, inventory]) => {
        if (!cancelled) {
          setReadiness(response.readiness ?? null);
          setReleases(inventory);
        }
      })
      .catch((cause) => { if (!cancelled) setError(cause instanceof Error ? cause.message : t('feedback.releaseGovernanceUnavailable')); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [t]);

  async function act(operation: () => Promise<unknown>) {
    if (running) return;
    setRunning(true);
    setError(null);
    try {
      await operation();
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : t('feedback.governedReleaseActionFailed'));
    } finally {
      setRunning(false);
    }
  }

  if (loading) {
    return <section className="card workspace-state" data-release-governance-state="loading" role="status"><h2><LocalizedText id="copy.evaluating_release_governance_evidence_71280780" /></h2><p><LocalizedText id="copy.evaluating_platform_evidence_this_may_take_a_few_sec_5515fca1" /></p><div className="metrics-grid" aria-hidden="true">{['Release', 'Build', 'Artifacts', 'Acceptance'].map((label) => <article className="metric-card" key={label}><small>{label}</small><strong>—</strong></article>)}</div></section>;
  }
  if (error && !readiness) {
    const forbidden = error.includes('permission');
    return <section className="card" data-release-governance-state={forbidden ? 'forbidden' : 'failed'}><h2><LocalizedText id="copy.release_governance_5f8db210" /></h2><p>{error}</p></section>;
  }

  const release: GovernedRelease | null = readiness?.release ?? null;
  const build: GovernedBuild | null = readiness?.build ?? null;
  const artifacts = readiness?.artifacts ?? [];
  const summary = readiness?.artifact_summary ?? {};
  const state = error
    ? (error.includes('permission') ? 'forbidden' : 'failed')
    : readiness?.status ?? 'empty';

  return (
    <section className="table-card" data-release-governance-state={state}>
      <div className="context-card-header"><h2><LocalizedText id="copy.release_governance_5f8db210" /></h2><span>{localizedProductLabel(readiness?.acceptance_status, t, t('status.notEvaluated'))}</span></div>
      {error ? <p className="form-error">{error}</p> : null}
      {!release ? (
        <div className="context-card" data-release-governance-state="empty">
          <h3><LocalizedText id="copy.create_governed_release_95764cbb" /></h3>
          <div className="form-grid">
            <Field label={t('copy.release_code_658e903e')} value={releaseCode} onChange={setReleaseCode} />
            <Field label={t('dynamic.version')} value={version} onChange={setVersion} />
            <label><LocalizedText id="copy.edition_64abb3cf" /><select value={edition} onChange={(event) => setEdition(event.target.value as 'community' | 'enterprise')}><option value="community"><LocalizedText id="copy.community_bfd58ee3" /></option><option value="enterprise"><LocalizedText id="copy.enterprise_b4afff31" /></option></select></label>
            <label><LocalizedText id="copy.channel_879f0b1b" /><select value={channel} onChange={(event) => setChannel(event.target.value)}><option value="development"><LocalizedText id="copy.development_4c17aadf" /></option><option value="acceptance"><LocalizedText id="copy.acceptance_a69d9d5f" /></option><option value="release_candidate"><LocalizedText id="copy.release_candidate_52bb6394" /></option><option value="stable"><LocalizedText id="copy.stable_d96e5b2d" /></option></select></label>
            <Field label={t('copy.source_repository_9110973f')} value={sourceRepository} onChange={setSourceRepository} />
            <Field label={t('copy.source_revision_acd4737a')} value={sourceRevision} onChange={setSourceRevision} />
          </div>
          <button className="secondary-button" type="button" disabled={running || !releaseCode || !version || !sourceRevision} onClick={() => act(() => createGovernedRelease({ release_code: releaseCode, version, edition, channel, source_repository: sourceRepository, source_revision: sourceRevision, idempotency_key: `portal-release-${releaseCode}` }))}><LocalizedText id="copy.create_release_e525dc62" /></button>
        </div>
      ) : (
        <>
          <div className="metrics-grid">
            <article className="metric-card"><small><LocalizedText id="copy.current_release_02a23472" /></small><strong>{release.release_code}</strong></article>
            <article className="metric-card"><small><LocalizedText id="copy.version_2da600bf" /></small><strong>{release.version}</strong></article>
            <article className="metric-card"><small><LocalizedText id="copy.edition_64abb3cf" /></small><strong>{release.edition}</strong></article>
            <article className="metric-card"><small><LocalizedText id="copy.channel_879f0b1b" /></small><strong>{release.channel}</strong></article>
            <article className="metric-card"><small><LocalizedText id="copy.source_revision_acd4737a" /></small><strong>{release.source_revision}</strong></article>
            <article className="metric-card"><small><LocalizedText id="copy.build_status_0ed31cea" /></small><strong>{localizedProductLabel(build?.build_status, t)}</strong></article>
            <article className="metric-card"><small><LocalizedText id="copy.build_timestamp_448710ed" /></small><strong>{text(build?.build_timestamp)}</strong></article>
            <article className="metric-card"><small><LocalizedText id="copy.target_61ad50a9" /></small><strong>{build ? `${build.target_platform}/${build.target_architecture}` : <LocalizedText id="copy.not_registered_998516e6" />}</strong></article>
            <article className="metric-card"><small><LocalizedText id="copy.build_manifest_023c76a7" /></small><strong>{readiness?.build_manifest ? <LocalizedText id="status.registered" /> : <LocalizedText id="copy.missing_92185dc5" />}</strong></article>
            <article className="metric-card"><small><LocalizedText id="copy.deployment_manifest_99e2220a" /></small><strong>{readiness?.deployment_manifest ? <LocalizedText id="status.registered" /> : <LocalizedText id="copy.missing_92185dc5" />}</strong></article>
            <article className="metric-card"><small><LocalizedText id="copy.required_artifacts_7e93fd04" /></small><strong>{text(summary.required, '0')}</strong></article>
            <article className="metric-card"><small><LocalizedText id="copy.verified_artifacts_d30535a1" /></small><strong>{text(summary.verified, '0')}</strong></article>
            <article className="metric-card"><small><LocalizedText id="copy.compatibility_5d60c7dd" /></small><strong>{text(readiness?.compatibility_summary.compatible, '0')}</strong></article>
            <article className="metric-card"><small><LocalizedText id="copy.migration_requirements_05db7747" /></small><strong>{text(readiness?.migration_summary.total, '0')}</strong></article>
            <article className="metric-card"><small><LocalizedText id="copy.rollback_target_12dcd055" /></small><strong>{readiness?.rollback_summary.configured ? <LocalizedText id="status.configured" /> : <LocalizedText id="copy.missing_92185dc5" />}</strong></article>
          </div>

          <div className="alerts-grid">
            <article className="context-card">
              <h3><LocalizedText id="copy.prepare_another_release_da535511" /></h3>
              <Field label={t('copy.release_code_658e903e')} value={releaseCode} onChange={setReleaseCode} />
              <Field label={t('dynamic.version')} value={version} onChange={setVersion} />
              <label><LocalizedText id="copy.edition_64abb3cf" /><select value={edition} onChange={(event) => setEdition(event.target.value as 'community' | 'enterprise')}><option value="community"><LocalizedText id="copy.community_bfd58ee3" /></option><option value="enterprise"><LocalizedText id="copy.enterprise_b4afff31" /></option></select></label>
              <label><LocalizedText id="copy.channel_879f0b1b" /><select value={channel} onChange={(event) => setChannel(event.target.value)}><option value="development"><LocalizedText id="copy.development_4c17aadf" /></option><option value="acceptance"><LocalizedText id="copy.acceptance_a69d9d5f" /></option><option value="release_candidate"><LocalizedText id="copy.release_candidate_52bb6394" /></option><option value="stable"><LocalizedText id="copy.stable_d96e5b2d" /></option></select></label>
              <Field label={t('copy.source_repository_9110973f')} value={sourceRepository} onChange={setSourceRepository} />
              <Field label={t('copy.source_revision_acd4737a')} value={sourceRevision} onChange={setSourceRevision} />
              <button className="secondary-button" type="button" disabled={running || !releaseCode || !version || !sourceRevision} onClick={() => act(() => createGovernedRelease({ release_code: releaseCode, version, edition, channel, source_repository: sourceRepository, source_revision: sourceRevision, idempotency_key: `portal-release-${releaseCode}` }))}><LocalizedText id="copy.create_release_e525dc62" /></button>
            </article>

            {!build ? <article className="context-card"><h3><LocalizedText id="copy.register_build_c774718c" /></h3><Field label={t('copy.build_number_4aac1875')} value={buildNumber} onChange={setBuildNumber} /><Field label={t('copy.build_timestamp_448710ed')} value={buildTimestamp} onChange={setBuildTimestamp} type="datetime-local" /><label><LocalizedText id="pages.workflows.section" /><select value={targetPlatform} onChange={(event) => setTargetPlatform(event.target.value)}><option value="container"><LocalizedText id="copy.container_e6443af9" /></option><option value="linux"><LocalizedText id="copy.linux_83ad8510" /></option><option value="darwin"><LocalizedText id="copy.darwin_695c30da" /></option><option value="windows"><LocalizedText id="copy.windows_26d9c28d" /></option><option value="other"><LocalizedText id="copy.other_6e6a6f20" /></option></select></label><label><LocalizedText id="copy.architecture_b040b417" /><select value={targetArchitecture} onChange={(event) => setTargetArchitecture(event.target.value)}><option value="multi_arch"><LocalizedText id="copy.multi_arch_cae087d0" /></option><option value="amd64"><LocalizedText id="copy.amd64_0a40ab6d" /></option><option value="arm64"><LocalizedText id="copy.arm64_bb16ce02" /></option><option value="other"><LocalizedText id="copy.other_6e6a6f20" /></option></select></label><button className="secondary-button" type="button" disabled={running || !buildNumber || !buildTimestamp} onClick={() => act(() => createGovernedBuild(release.id, { build_number: buildNumber, build_timestamp: new Date(buildTimestamp).toISOString(), builder_type: 'manual_evidence', source_revision: release.source_revision, target_platform: targetPlatform, target_architecture: targetArchitecture, build_profile: configurationProfile, reproducibility_evidence: {}, idempotency_key: `portal-build-${release.id}-${buildNumber}` }))}><LocalizedText id="copy.register_build_c774718c" /></button></article> : null}

            {build && !readiness?.build_manifest ? <article className="context-card"><h3><LocalizedText id="copy.build_manifest_023c76a7" /></h3><Field label={t('copy.python_version_63a49d02')} value={pythonVersion} onChange={setPythonVersion} /><Field label={t('copy.node_version_c0881987')} value={nodeVersion} onChange={setNodeVersion} /><Field label={t('copy.database_revision_cdea81d2')} value={schemaRevision} onChange={setSchemaRevision} /><Field label={t('copy.configuration_profile_9fb5274e')} value={configurationProfile} onChange={setConfigurationProfile} /><button className="secondary-button" type="button" disabled={running || !schemaRevision} onClick={() => act(async () => { await registerGovernedBuildManifest(build.id, { manifest_version: '1', application_version: release.version, source_revision: release.source_revision, build_timestamp: build.build_timestamp, python_version: pythonVersion || undefined, node_version: nodeVersion || undefined, database_schema_revision: schemaRevision, target_platforms: [build.target_platform], target_architectures: [build.target_architecture], dependency_summary: { evidence_source: 'operator_registered' }, component_versions: { api: release.version, portal: release.version, workers: release.version, scheduler: release.version, migrator: schemaRevision, object_storage_integration: release.version, database_compatibility: schemaRevision }, configuration_profile: configurationProfile, manifest_payload: { evidence_source: 'operator_registered' } }); await completeGovernedBuild(build.id, { reproducibility_evidence: {}, result_evidence: { manifest_registered: true } }); })}><LocalizedText id="copy.register_manifest_and_complete_build_e3dbf352" /></button></article> : null}

            {build && !readiness?.deployment_manifest ? <article className="context-card"><h3><LocalizedText id="copy.deployment_manifest_99e2220a" /></h3><Field label={t('copy.required_artifact_codes_7b68cb18')} value={requiredArtifactCodes} onChange={setRequiredArtifactCodes} /><label><LocalizedText id="copy.rollback_target_12dcd055" /><select value={rollbackTarget} onChange={(event) => setRollbackTarget(event.target.value)}><option value=""><LocalizedText id="copy.select_a_governed_release_9879c80d" /></option>{releases.filter((item) => item.id !== release.id && item.edition === release.edition).map((item) => <option key={item.id} value={item.id}>{item.release_code} · {item.version}</option>)}</select></label><button className="secondary-button" type="button" disabled={running || !rollbackTarget} onClick={() => act(() => registerGovernedDeploymentManifest(release.id, { build_id: build.id, manifest_version: '1', deployment_profile: 'on_premise', deployment_strategy: 'external', required_services: ['api', 'portal', 'postgresql', 'migrator'], optional_services: ['ai_provider', 'vector_database'], health_checks: [{ service: 'api', check: 'liveness' }], readiness_checks: [{ service: 'api', check: 'readiness' }], startup_order: ['postgresql', 'migrator', 'api', 'portal'], configuration_requirements: { profile: configurationProfile }, secret_requirements: ['database_credentials', 'object_storage_credentials'], storage_requirements: { database: 'persistent', object_storage: 'persistent' }, network_requirements: { encrypted_external_transport: true }, resource_requirements: { evidence_required: true }, migration_requirements: { target_revision: schemaRevision }, rollback_target_release_id: rollbackTarget, rollback_procedure_reference: 'governed-external-procedure', manifest_payload: { required_artifact_codes: list(requiredArtifactCodes), required_compatibility_types: ['database_schema', 'previous_release'] } }))}><LocalizedText id="copy.register_deployment_manifest_e4a0115a" /></button></article> : null}

            <article className="context-card"><h3><LocalizedText id="copy.register_artifact_e51fe602" /></h3><Field label={t('copy.artifact_code_e589a13b')} value={artifactCode} onChange={setArtifactCode} /><label><LocalizedText id="common.type" /><select value={artifactType} onChange={(event) => setArtifactType(event.target.value)}><option value="container_image"><LocalizedText id="copy.container_image_2efa4dd1" /></option><option value="portal_bundle"><LocalizedText id="copy.portal_bundle_a1238cf8" /></option><option value="migration_bundle"><LocalizedText id="copy.migration_bundle_39b5e28c" /></option><option value="source_bundle"><LocalizedText id="copy.source_bundle_43383a58" /></option><option value="other"><LocalizedText id="copy.other_6e6a6f20" /></option></select></label><Field label={t('copy.component_c92c529e')} value={artifactComponent} onChange={setArtifactComponent} /><Field label={t('copy.logical_reference_a4bde09d')} value={artifactReference} onChange={setArtifactReference} /><Field label={t('copy.sha_256_checksum_f8a14f81')} value={checksum} onChange={setChecksum} /><Field label={t('copy.oci_or_file_digest_dc89b69d')} value={digest} onChange={setDigest} /><button className="secondary-button" type="button" disabled={running || !build || !artifactCode || !artifactReference || !checksum || !digest} onClick={() => act(() => registerGovernedArtifact(release.id, { build_id: build?.id, artifact_code: artifactCode, artifact_type: artifactType, component: artifactComponent, edition: release.edition, platform: build?.target_platform, architecture: build?.target_architecture, media_type: artifactType === 'container_image' ? 'application/vnd.oci.image.manifest.v1+json' : 'application/octet-stream', artifact_reference: artifactReference, checksum_algorithm: 'sha256', checksum, digest_algorithm: digest.startsWith('sha256:') ? 'sha256' : 'external', digest, signature_status: 'not_provided', provenance_status: 'pending', sbom_status: 'pending', required: true, metadata_payload: { evidence_source: 'operator_registered' } }))}><LocalizedText id="copy.register_artifact_e51fe602" /></button></article>

            <article className="context-card"><h3><LocalizedText id="copy.compatibility_5d60c7dd" /></h3><label><LocalizedText id="common.type" /><select value={compatibilityType} onChange={(event) => setCompatibilityType(event.target.value)}><option value="database_schema"><LocalizedText id="copy.database_schema_41ba9923" /></option><option value="previous_release"><LocalizedText id="copy.previous_release_bce4501c" /></option><option value="postgresql"><LocalizedText id="copy.postgresql_24fd6c2d" /></option><option value="redis"><LocalizedText id="copy.redis_24071b57" /></option><option value="object_storage"><LocalizedText id="copy.object_storage_4f611774" /></option><option value="container_runtime"><LocalizedText id="copy.container_runtime_06515d1d" /></option></select></label><Field label={t('copy.minimum_version_2e0596e8')} value={minimumVersion} onChange={setMinimumVersion} /><Field label={t('copy.maximum_version_665b0310')} value={maximumVersion} onChange={setMaximumVersion} /><Field label={t('copy.evidence_reference_38221c4d')} value={compatibilityEvidence} onChange={setCompatibilityEvidence} /><button className="secondary-button" type="button" disabled={running || !compatibilityEvidence} onClick={() => act(() => registerReleaseCompatibility(release.id, { compatibility_type: compatibilityType, minimum_version: minimumVersion || undefined, maximum_version: maximumVersion || undefined, compatible: true, requirements: {}, evidence_payload: { evidence_reference: compatibilityEvidence } }))}><LocalizedText id="copy.register_compatibility_13337b28" /></button></article>

            <article className="context-card"><h3><LocalizedText id="copy.migration_requirements_05db7747" /></h3><Field label={t('copy.from_revision_9e3c6563')} value={migrationFrom} onChange={setMigrationFrom} /><Field label={t('copy.to_revision_b55f1f4c')} value={migrationTo} onChange={setMigrationTo} /><label><LocalizedText id="copy.strategy_69fb26dd" /><select value={migrationStrategy} onChange={(event) => setMigrationStrategy(event.target.value)}><option value="forward_only"><LocalizedText id="copy.forward_only_cfb1ebad" /></option><option value="expand_contract"><LocalizedText id="copy.expand_contract_95b60972" /></option><option value="offline"><LocalizedText id="copy.offline_e01fa717" /></option><option value="external"><LocalizedText id="copy.external_8d10c693" /></option><option value="none"><LocalizedText id="common.none" /></option></select></label><Field label={t('copy.evidence_reference_38221c4d')} value={migrationEvidence} onChange={setMigrationEvidence} /><button className="secondary-button" type="button" disabled={running || !migrationTo || !migrationEvidence} onClick={() => act(() => registerReleaseMigration(release.id, { from_revision: migrationFrom || undefined, to_revision: migrationTo, migration_required: migrationStrategy !== 'none', migration_strategy: migrationStrategy, reversible: migrationStrategy === 'none' || migrationStrategy === 'expand_contract', irreversible_reason: migrationStrategy !== 'none' && migrationStrategy !== 'expand_contract' ? 'Forward-only governed migration evidence' : undefined, preconditions: [], postconditions: [], evidence_payload: { evidence_reference: migrationEvidence } }))}><LocalizedText id="copy.register_migration_073e63e7" /></button></article>

            <article className="context-card"><h3><LocalizedText id="copy.rollback_target_12dcd055" /></h3><label><LocalizedText id="copy.target_release_505033cd" /><select value={rollbackTarget} onChange={(event) => setRollbackTarget(event.target.value)}><option value=""><LocalizedText id="copy.select_a_governed_release_9879c80d" /></option>{releases.filter((item) => item.id !== release.id && item.edition === release.edition).map((item) => <option key={item.id} value={item.id}>{item.release_code} · {item.version}</option>)}</select></label><Field label={t('copy.evidence_reference_38221c4d')} value={rollbackEvidence} onChange={setRollbackEvidence} /><button className="secondary-button" type="button" disabled={running || !rollbackTarget || !rollbackEvidence} onClick={() => act(() => registerReleaseRollback(release.id, { rollback_target_release_id: rollbackTarget, rollback_supported: true, rollback_strategy: 'external', database_rollback_supported: false, application_rollback_supported: true, required_actions: [{ action: 'restore_previous_application_artifacts' }], blockers: [], evidence_payload: { evidence_reference: rollbackEvidence }, verified_at: new Date().toISOString() }))}><LocalizedText id="copy.register_rollback_target_e3484287" /></button></article>
          </div>

          <h3><LocalizedText id="copy.governed_artifacts_8a055771" /></h3>
          {artifacts.length ? <table><thead><tr><th><LocalizedText id="copy.artifact_aa778b50" /></th><th><LocalizedText id="copy.component_c92c529e" /></th><th><LocalizedText id="common.status" /></th><th><LocalizedText id="copy.checksum_d8fcd1cd" /></th><th><LocalizedText id="copy.digest_47fdd58b" /></th><th><LocalizedText id="copy.provenance_dd35a816" /></th><th><LocalizedText id="copy.sbom_bc385b71" /></th><th><LocalizedText id="copy.action_97c89a4d" /></th></tr></thead><tbody>{artifacts.map((artifact: GovernedArtifact) => <tr key={artifact.id}><td>{artifact.artifact_code}</td><td>{artifact.component}</td><td>{localizedProductLabel(artifact.status, t)}</td><td>{artifact.checksum ? <LocalizedText id="status.registered" /> : <LocalizedText id="copy.missing_92185dc5" />}</td><td>{artifact.digest ? <LocalizedText id="status.registered" /> : <LocalizedText id="copy.missing_92185dc5" />}</td><td>{localizedProductLabel(artifact.provenance_status, t)}</td><td>{localizedProductLabel(artifact.sbom_status, t)}</td><td><button className="secondary-button" type="button" disabled={running || artifact.status === 'verified'} onClick={() => act(() => verifyGovernedArtifact(artifact.id, { checksum_verified: true, digest_verified: true, provenance_status: 'verified', sbom_status: 'available', signature_status: 'not_provided', evidence_payload: { evidence_source: 'controlled_operator_evidence' } }))}><LocalizedText id="copy.verify_evidence_3e8358ab" /></button></td></tr>)}</tbody></table> : <p><LocalizedText id="copy.no_artifacts_are_registered_dd40dfeb" /></p>}

          <div className="alerts-grid">
            <article className="context-card"><strong><LocalizedText id="copy.blockers_699edf83" /></strong>{readiness?.blockers.length ? <ul className="compact-list">{readiness.blockers.map((item, index) => <li key={`release-blocker-${index}`}>{issue(item)}</li>)}</ul> : <p><LocalizedText id="copy.no_blockers_f1cd5e39" /></p>}</article>
            <article className="context-card"><strong><LocalizedText id="copy.warnings_1430f976" /></strong>{readiness?.warnings.length ? <ul className="compact-list">{readiness.warnings.map((item, index) => <li key={`release-warning-${index}`}>{issue(item)}</li>)}</ul> : <p><LocalizedText id="copy.no_warnings_ddf1e74c" /></p>}</article>
            <article className="context-card"><strong><LocalizedText id="copy.next_actions_7b09055a" /></strong>{readiness?.next_actions.length ? <ul className="compact-list">{readiness.next_actions.map((item, index) => <li key={`release-action-${index}`}>{localizedProductLabel(item.action, t)}</li>)}</ul> : <p><LocalizedText id="copy.no_actions_required_8ccb2b77" /></p>}</article>
          </div>
          <button className="secondary-button" type="button" disabled={running} onClick={() => act(() => evaluateGovernedRelease(release.id))}>{running ? <LocalizedText id="copy.persisting_evidence_0a5665f6" /> : <LocalizedText id="copy.evaluate_release_acceptance_ecf72f50" />}</button>
        </>
      )}
    </section>
  );
}
