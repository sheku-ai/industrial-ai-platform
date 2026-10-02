from app.services.protected_document_composition import compose_protected_document_adapter
from app.services.protected_document_runtime_adapter import ProtectedDocumentRuntimeAdapter
from app.services.secret_store import InMemorySecretStore


class Delegate:
    execution_type = "document.ingestion"

    def execute(self, item, heartbeat):
        raise AssertionError("not executed")


def test_composition_wraps_document_ingestion_adapter() -> None:
    delegate = Delegate()
    store = InMemorySecretStore()

    def session_factory():
        return None

    adapter = compose_protected_document_adapter(
        delegate,
        secret_store=store,
        session_factory=session_factory,
    )

    assert isinstance(adapter, ProtectedDocumentRuntimeAdapter)
    assert adapter.execution_type == "document.ingestion"
    assert adapter._delegate is delegate
    assert adapter._secret_store is store
    assert adapter._session_factory is session_factory
