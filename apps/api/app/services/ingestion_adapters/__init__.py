"""Provider-neutral ingestion adapter implementations.

Adapters are imported from their concrete modules so optional format-specific
dependencies are loaded only when that adapter is registered.

Examples:
    from app.services.ingestion_adapters.text import PlainTextIngestionAdapter
    from app.services.ingestion_adapters.pdf import PdfIngestionAdapter

Adapters extract content only. They do not own persistence, runtime lifecycle,
artifact publication, retries, embeddings or vector writes.
"""
