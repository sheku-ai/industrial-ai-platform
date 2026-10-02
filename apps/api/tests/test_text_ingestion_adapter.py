from uuid import uuid4

from app.services.ingestion_adapter_contracts import AdapterExecutionStatus, AdapterInput
from app.services.text_ingestion_adapter import TextAdapterOptions, TextIngestionAdapter


def make_request(file_name: str, media_type: str) -> AdapterInput:
    return AdapterInput(
        organization_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        source_reference=f"memory://{file_name}",
        original_file_name=file_name,
        declared_media_type=media_type,
        checksum_sha256="a" * 64,
        content_length=128,
        idempotency_key="text-adapter-test",
    )


def test_plain_text_execution_is_non_ai() -> None:
    payload = ("Header\n\n" + "content " * 80).encode("utf-8")
    result = TextIngestionAdapter().execute_bytes(
        make_request("source.txt", "text/plain"),
        payload,
        TextAdapterOptions(max_chars=300, overlap=50),
    )
    assert result.status == AdapterExecutionStatus.SUCCEEDED
    assert len(result.chunks) >= 2
    assert result.metrics["embedding_generated"] is False
    assert result.metrics["vector_indexed"] is False
    assert result.metrics["llm_used"] is False


def test_html_normalization_removes_script_content() -> None:
    payload = b"<html><script>ignore me</script><body><h1>Title</h1><p>Useful content.</p></body></html>"
    result = TextIngestionAdapter().execute_bytes(make_request("source.html", "text/html"), payload)
    combined = " ".join(chunk.text for chunk in result.chunks)
    assert result.status == AdapterExecutionStatus.SUCCEEDED
    assert "Useful content" in combined
    assert "ignore me" not in combined


def test_json_and_csv_are_normalized() -> None:
    json_result = TextIngestionAdapter().execute_bytes(
        make_request("source.json", "application/json"),
        b'{"name":"generic","enabled":true}',
    )
    csv_result = TextIngestionAdapter().execute_bytes(
        make_request("source.csv", "text/csv"),
        b"name,value\nalpha,1\nbeta,2\n",
    )
    assert json_result.status == AdapterExecutionStatus.SUCCEEDED
    assert "generic" in json_result.chunks[0].text
    assert csv_result.status == AdapterExecutionStatus.SUCCEEDED
    assert "alpha | 1" in csv_result.chunks[0].text


def test_rich_document_is_rejected_by_text_adapter() -> None:
    result = TextIngestionAdapter().execute_bytes(
        make_request("source.pdf", "application/pdf"),
        b"not a rich document",
    )
    assert result.status == AdapterExecutionStatus.FAILED
    assert result.error_code == "unsupported_text_adapter_format"
