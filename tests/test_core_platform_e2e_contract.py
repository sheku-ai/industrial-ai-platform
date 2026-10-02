from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "e2e_core_platform.py"


def test_core_e2e_uses_fixed_supported_ports() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'API_BASE_URL = "http://127.0.0.1:8000"' in source
    assert 'PORTAL_URL = "http://127.0.0.1:3000/operations"' in source
    assert '"API_PORT": "8000"' in source
    assert '"PORTAL_PORT": "3000"' in source


def test_core_e2e_disables_optional_ai_dependencies() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert '"FEATURE_EMBEDDINGS_ENABLED": "false"' in source
    assert '"FEATURE_VECTOR_RETRIEVAL_ENABLED": "false"' in source
    assert '"CONTAINER_OBJECT_STORAGE_ENDPOINT_URL": ""' in source
    assert '"ai_required": False' in source


def test_core_e2e_verifies_api_and_postgresql_persistence_across_restart() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert '"POST",\n            "/api/core/organizations"' in source
    assert "verify_postgresql(slug, env=env)" in source
    assert '"resource_retrieved_before_restart"' in source
    assert '"stack_restarted"' in source
    assert '"resource_persisted_after_restart"' in source
    assert '"DELETE", f"/api/core/organizations/{resource_id}"' in source


def test_core_e2e_performs_clean_shutdown_and_writes_evidence() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'SUPERVISOR), "compose-down"' in source
    assert 'EVIDENCE_PATH = ROOT / "runtime" / "evidence" / "core-platform-e2e.json"' in source
    assert "write_evidence(evidence)" in source
    assert 'evidence["status"] = "passed"' in source
