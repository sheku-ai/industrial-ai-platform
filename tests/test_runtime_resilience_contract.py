from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_runtime_resilience.py"


def test_resilience_validation_is_bounded_and_uses_fixed_api_port() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'API_BASE_URL = "http://127.0.0.1:8000"' in source
    assert "default=200" in source
    assert "default=20" in source
    assert "default=25" in source
    assert '"bounded": True' in source


def test_resilience_validation_disables_optional_ai_services() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"FEATURE_EMBEDDINGS_ENABLED": "false"' in source
    assert '"FEATURE_VECTOR_RETRIEVAL_ENABLED": "false"' in source
    assert '"CONTAINER_OBJECT_STORAGE_ENDPOINT_URL": ""' in source
    assert '"ai_required": False' in source


def test_resilience_validation_covers_load_concurrency_and_recovery() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'concurrent_gets("/health/live"' in source
    assert 'concurrent_gets("/health/ready"' in source
    assert "concurrent_resource_cycle(" in source
    assert '["docker", "compose", "restart", "api"]' in source
    assert '"api_restart_recovered"' in source
    assert '"dependencies_recovered"' in source


def test_resilience_validation_records_latency_and_evidence() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"p95"' in source
    assert '"throughput_rps"' in source
    assert "runtime-resilience.json" in source
    assert '"clean_shutdown"' in source
