from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "e2e_optional_ingestion.py"


def test_optional_ingestion_e2e_uses_fixed_api_port() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'API_BASE_URL = "http://127.0.0.1:8000"' in source
    assert "optional-ingestion-e2e.json" in source


def test_optional_ingestion_e2e_disables_ai_dependencies() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"FEATURE_EMBEDDINGS_ENABLED": "false"' in source
    assert '"FEATURE_VECTOR_RETRIEVAL_ENABLED": "false"' in source
    assert '"CONTAINER_OBJECT_STORAGE_ENDPOINT_URL": ""' in source
    assert '"ai_required": False' in source
    assert '"embedding_enabled": False' in source
    assert '"retrieval_mode": "lexical_only"' in source


def test_optional_ingestion_e2e_covers_full_control_plane_flow() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"/api/ingestion/register"' in source
    assert '"/api/ingestion/jobs/claim"' in source
    assert 'f"/api/ingestion/jobs/{job_id}/transition"' in source
    assert '"/api/documents/chunks/persist"' in source
    assert '"/api/indexing/jobs"' in source
    assert 'f"/api/indexing/jobs/{indexing_job_id}/run"' in source
    assert '"/api/knowledge/search"' in source


def test_optional_ingestion_e2e_verifies_non_ai_metrics_and_postgresql() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "embedding_generated" in source
    assert "llm_used" in source
    assert "vector_retrieval_enabled" in source
    assert "embedding_execution_enabled" in source
    assert '"1|1|1|1|1"' in source


def test_optional_ingestion_e2e_cleans_temporary_data_and_stack() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "def cleanup(" in source
    assert "DELETE FROM documents.indexing_jobs" in source
    assert "DELETE FROM core.organizations" in source
    assert '"temporary_data_cleaned"' in source
    assert 'SUPERVISOR), "compose-down"' in source
    assert '"clean_shutdown"' in source
