from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "apps/api"


def main() -> int:
    helper = (API_ROOT / "app/testing/test_data.py").read_text(encoding="utf-8")
    inventory = (API_ROOT / "scripts/inventory_test_organizations.py").read_text(encoding="utf-8")
    writer_inventory = (API_ROOT / "scripts/inventory_persistent_test_writers.py").read_text(encoding="utf-8")
    writer_classifier = (API_ROOT / "scripts/classify_persistent_test_writers.py").read_text(encoding="utf-8")
    counter = (API_ROOT / "scripts/count_test_organizations.py").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.test.yml").read_text(encoding="utf-8")
    ingestion_overlay = (ROOT / "docker-compose.ingestion-test.yml").read_text(encoding="utf-8")

    runner_names = (
        "run_runtime_isolated_domain_tests",
        "run_database_only_persistent_writer_tests",
        "run_ingestion_multimodal_isolated_tests",
        "run_runtime_lease_domain_tests",
        "run_runtime_worker_domain_tests",
        "run_sprint_26_3_gate",
    )
    runners = {name: (ROOT / f"scripts/{name}.py").read_text(encoding="utf-8") for name in runner_names}
    wrappers = {name: (ROOT / f"scripts/{name}.ps1").read_text(encoding="utf-8") for name in runner_names}
    gate = runners["run_sprint_26_3_gate"]
    consolidated_runner = runners["run_runtime_isolated_domain_tests"]
    database_only_runner = runners["run_database_only_persistent_writer_tests"]
    ingestion_runner = runners["run_ingestion_multimodal_isolated_tests"]
    lease_runner = runners["run_runtime_lease_domain_tests"]
    worker_runner = runners["run_runtime_worker_domain_tests"]
    managed_services = (API_ROOT / "scripts/check_runtime_managed_services_e2e.py").read_text(encoding="utf-8")

    lease_scripts = [
        API_ROOT / "scripts/check_runtime_lease_retry_e2e.py",
        API_ROOT / "scripts/check_runtime_lease_exhaustion_e2e.py",
        API_ROOT / "scripts/check_runtime_lease_invalid_payload_e2e.py",
        API_ROOT / "scripts/check_runtime_lease_concurrency_e2e.py",
    ]
    worker_scripts = [
        API_ROOT / "scripts/check_runtime_worker_control_e2e.py",
        API_ROOT / "scripts/check_runtime_worker_health_e2e.py",
        API_ROOT / "scripts/check_runtime_worker_readiness_api_e2e.py",
        API_ROOT / "scripts/check_runtime_worker_command_audit_e2e.py",
        API_ROOT / "scripts/check_runtime_worker_stale_audit_e2e.py",
        API_ROOT / "scripts/check_runtime_worker_history_api_e2e.py",
        API_ROOT / "scripts/check_runtime_worker_summary_e2e.py",
    ]
    database_only_scripts = [
        API_ROOT / "scripts/check_multimodal_retrieval_postgres_e2e.py",
        API_ROOT / "scripts/check_processing_revision_selection_e2e.py",
        API_ROOT / "scripts/check_visual_chunk_concurrency_e2e.py",
        API_ROOT / "scripts/check_visual_chunk_revision_idempotency_e2e.py",
    ]
    ingestion_scripts = [
        API_ROOT / "scripts/check_worker_multimodal_full_chain_contract_e2e.py",
        API_ROOT / "scripts/check_worker_multimodal_full_chain_e2e.py",
        API_ROOT / "scripts/check_worker_multimodal_publication_e2e.py",
        API_ROOT / "scripts/check_worker_visual_enrichment_producer_e2e.py",
        API_ROOT / "scripts/check_worker_visual_enrichment_producer_e2e_v2.py",
        API_ROOT / "scripts/smoke_pdf_ingestion_e2e.py",
        API_ROOT / "scripts/smoke_pdf_multisegment_resume.py",
        API_ROOT / "scripts/smoke_protected_pdf_detection_e2e.py",
        API_ROOT / "scripts/smoke_protected_pdf_retry_e2e.py",
        API_ROOT / "scripts/smoke_text_ingestion_e2e.py",
    ]
    isolated_scripts = lease_scripts + worker_scripts
    ingestion_sources = [path.read_text(encoding="utf-8") for path in ingestion_scripts]

    checks = {
        "disposable_postgres_defined": "postgres-test:" in compose,
        "test_database_isolated": "industrial_ai_test" in compose,
        "test_database_uses_tmpfs": "tmpfs:" in compose,
        "test_migrator_defined": "migrator-test:" in compose,
        "ephemeral_lifecycle_metadata": '"lifecycle": "ephemeral"' in helper,
        "test_environment_metadata": '"environment": "test"' in helper,
        "expiry_metadata": '"expires_at"' in helper,
        "inventory_is_preview_only": '"mode": "preview"' in inventory and "delete(" not in inventory.lower(),
        "stable_organizations_protected": "PROTECTED_SLUGS" in inventory and '"smoke-org"' in inventory,
        "legacy_inventory_supported": "LEGACY_PREFIXES" in inventory,
        "writer_inventory_scans_all_scripts": 'SCRIPTS_ROOT.glob("*.py")' in writer_inventory,
        "writer_inventory_detects_organization_constructor": "organization_constructor" in writer_inventory,
        "writer_inventory_detects_raw_sql": "raw_organization_insert" in writer_inventory,
        "writer_inventory_reports_unclassified": "unclassified_writer_count" in writer_inventory,
        "writer_classifier_has_database_profile": "database_only" in writer_classifier,
        "writer_classifier_has_external_profile": "object_storage_and_worker" in writer_classifier,
        "writer_classifier_excludes_lifecycle_aware": "uses_ephemeral_helper" in writer_classifier,
        "database_only_runner_uses_test_compose": "docker-compose.test.yml" in database_only_runner,
        "database_only_runner_disposes_environment": "finally:" in database_only_runner
        and database_only_runner.count("compose.down()") >= 2,
        "database_only_runner_executes_all_checks": all(
            path.name in database_only_runner for path in database_only_scripts
        ),
        "ingestion_overlay_defines_redis": "redis-test:" in ingestion_overlay,
        "ingestion_overlay_defines_minio": "minio-test:" in ingestion_overlay,
        "ingestion_overlay_defines_worker": "ingestion-worker-test:" in ingestion_overlay,
        "ingestion_overlay_defines_api_server": "api-server-test:" in ingestion_overlay,
        "ingestion_overlay_api_server_has_healthcheck": "openapi.json" in ingestion_overlay,
        "ingestion_overlay_uses_disposable_database": "industrial_ai_test" in ingestion_overlay,
        "ingestion_overlay_has_no_literal_credentials": "minioadmin" not in ingestion_overlay,
        "ingestion_runner_uses_both_compose_files": "docker-compose.test.yml" in ingestion_runner
        and "docker-compose.ingestion-test.yml" in ingestion_runner,
        "ingestion_runner_generates_ephemeral_credentials": 'ensure_ephemeral("TEST_MINIO_ACCESS_KEY"'
        in ingestion_runner
        and 'ensure_ephemeral("TEST_MINIO_SECRET_KEY"' in ingestion_runner,
        "ingestion_runner_separates_embedded_and_daemon_workers": "EMBEDDED_WORKER_CHECKS" in ingestion_runner
        and "DAEMON_WORKER_CHECKS" in ingestion_runner,
        "ingestion_runner_waits_for_api_server": '["up", "-d", "--wait", "api-server-test", "ingestion-worker-test"]'
        in ingestion_runner,
        "ingestion_runner_disposes_environment": "finally:" in ingestion_runner
        and ingestion_runner.count("compose.down()") >= 2,
        "ingestion_runner_executes_all_checks": all(path.name in ingestion_runner for path in ingestion_scripts),
        "isolated_ingestion_e2es_preserve_append_only_runtime_evidence": all(
            "delete(RuntimeExecution)" not in source
            and "session.delete(execution" not in source
            and "cleanup.delete(execution" not in source
            for source in ingestion_sources
        ),
        "visual_producer_uses_canonical_provider_key": (
            'first_visual.get("provider_key") == "deterministic-local-vision"' in ingestion_sources[3]
        ),
        "counter_reuses_inventory_classification": "from scripts.inventory_test_organizations import classify"
        in counter,
        "managed_services_e2e_is_read_only": "session.add(" not in managed_services
        and "session.delete(" not in managed_services,
        "lease_suite_uses_shared_helper": all(
            "create_ephemeral_organization" in path.read_text(encoding="utf-8") for path in lease_scripts
        ),
        "targeted_lease_runner_available": all(path.name in lease_runner for path in lease_scripts),
        "targeted_lease_runner_disposes_environment": "finally:" in lease_runner
        and lease_runner.count("compose.down()") >= 2,
        "targeted_worker_runner_available": all(path.name in worker_runner for path in worker_scripts),
        "targeted_worker_runner_disposes_environment": "finally:" in worker_runner
        and worker_runner.count("compose.down()") >= 2,
        "consolidated_runner_uses_test_compose": "docker-compose.test.yml" in consolidated_runner,
        "consolidated_runner_disposes_environment": "finally:" in consolidated_runner
        and consolidated_runner.count("compose.down()") >= 2,
        "consolidated_runner_executes_all_checks": all(path.name in consolidated_runner for path in isolated_scripts),
        "consolidated_runner_migrates_once": consolidated_runner.count('compose.run(["run", "--rm", "migrator-test"])')
        == 1,
        "all_powershell_wrappers_are_thin": all(
            len([line for line in text.splitlines() if line.strip()]) <= 15 for text in wrappers.values()
        ),
        "all_powershell_wrappers_have_no_compose_logic": all(
            "docker compose" not in text.lower() for text in wrappers.values()
        ),
        "all_powershell_wrappers_propagate_exit_code": all("exit $LASTEXITCODE" in text for text in wrappers.values()),
        "full_gate_invokes_consolidated_runner": "run_runtime_isolated_domain_tests.py" in gate,
        "full_gate_invokes_ingestion_runner": "run_ingestion_multimodal_isolated_tests.py" in gate,
        "full_gate_does_not_invoke_powershell": ".ps1" not in gate,
        "full_gate_does_not_invoke_targeted_runners": "run_runtime_lease_domain_tests" not in gate
        and "run_runtime_worker_domain_tests" not in gate,
        "full_gate_does_not_run_isolated_checks_on_dev_api": all(
            gate.count(path.name) == 0 for path in isolated_scripts + ingestion_scripts
        ),
        "full_gate_captures_test_data_baseline": "baseline = count_test_organizations" in gate,
        "full_gate_checks_test_data_final_count": "final_count = count_test_organizations" in gate,
        "full_gate_fails_on_test_data_growth": "Persistent test organization count changed during gate" in gate,
    }
    result = {**checks, "passed": all(checks.values())}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
