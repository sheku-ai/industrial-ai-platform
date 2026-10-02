"""Diversity selection for Retrieval Orchestration."""

from __future__ import annotations

from app.services.retrieval.contracts import MergedRetrievalCandidate, RetrievalQuery
from app.services.retrieval.interfaces import DiversitySelector


class ContentAwareDiversitySelector(DiversitySelector):
    """Selects diverse candidates for context.

    The selector avoids repeated content hashes and limits repeated document
    versions when possible. It is generic and does not encode domain concepts.
    """

    def __init__(self, max_per_document_version: int = 3) -> None:
        self.max_per_document_version = max_per_document_version

    def select(
        self,
        query: RetrievalQuery,
        candidates: tuple[MergedRetrievalCandidate, ...],
    ) -> tuple[MergedRetrievalCandidate, ...]:
        if not query.enable_diversity:
            return candidates[: query.top_k]

        selected: list[MergedRetrievalCandidate] = []
        seen_hashes: set[str] = set()
        per_version: dict[str, int] = {}

        for candidate in candidates:
            content_hash = candidate.candidate.content_hash
            version_key = str(candidate.candidate.document_version_id)

            if content_hash and content_hash in seen_hashes:
                continue

            if per_version.get(version_key, 0) >= self.max_per_document_version:
                continue

            selected.append(candidate)
            if content_hash:
                seen_hashes.add(content_hash)
            per_version[version_key] = per_version.get(version_key, 0) + 1

            if len(selected) >= query.top_k:
                break

        if len(selected) < min(query.top_k, len(candidates)):
            selected_ids = {item.candidate.chunk_id for item in selected}
            for candidate in candidates:
                if candidate.candidate.chunk_id not in selected_ids:
                    selected.append(candidate)
                if len(selected) >= query.top_k:
                    break

        return tuple(selected[: query.top_k])
