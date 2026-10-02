"""In-memory knowledge store for runtime publication smoke paths."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Any


@dataclass
class InMemoryKnowledgeStore:
    """Process-local store for published chunk records.

    This is intentionally not durable. It provides the first executable
    publication target while keeping the runtime provider-neutral.
    """

    _records: dict[tuple[str, int, str], dict[str, Any]] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock)

    def publish_chunks(self, chunks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        published: list[dict[str, Any]] = []
        duplicates: list[dict[str, Any]] = []
        with self._lock:
            for chunk in chunks:
                key = (
                    str(chunk.get("artifact_id") or ""),
                    int(chunk.get("chunk_index")),
                    str(chunk.get("content_hash") or ""),
                )
                existing = self._records.get(key)
                if existing is not None:
                    duplicates.append(existing)
                    published.append(existing)
                    continue
                self._records[key] = dict(chunk)
                published.append(dict(chunk))
        return published, duplicates

    def list_records(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._records.values()]

    def has_records(self) -> bool:
        with self._lock:
            return bool(self._records)

    def record_count(self) -> int:
        with self._lock:
            return len(self._records)

    def reset(self) -> None:
        with self._lock:
            self._records.clear()


_MEMORY_KNOWLEDGE_STORE = InMemoryKnowledgeStore()


def get_memory_knowledge_store() -> InMemoryKnowledgeStore:
    return _MEMORY_KNOWLEDGE_STORE
