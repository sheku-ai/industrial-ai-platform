"""Deterministic rule-based reranking for Knowledge Runtime.

Sprint 11.4 introduces transparent scoring rules on top of PostgreSQL FTS.

Design constraints:
- no LLM dependency;
- no model-based reranking dependency;
- no vector dependency;
- no customer-specific taxonomy;
- score contributions are exposed in candidate metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.retrieval.query_normalization import QueryNormalizationResult


@dataclass(frozen=True)
class RuleRerankTrace:
    """Transparent scoring trace for a candidate."""

    original_score: float
    rerank_score: float
    final_score: float
    rules: dict[str, float] = field(default_factory=dict)

    def as_metadata(self) -> dict[str, object]:
        return {
            "reranker": "deterministic_rules_v1",
            "original_score": self.original_score,
            "rerank_score": self.rerank_score,
            "final_score": self.final_score,
            "rules": self.rules,
        }


def rerank_candidates(candidates: tuple, normalized: QueryNormalizationResult) -> tuple:
    """Apply deterministic rule-based reranking to retrieval candidates."""

    reranked = []
    for candidate in candidates:
        trace = _score_candidate(candidate, normalized)
        metadata = dict(candidate.metadata or {})
        metadata["rerank"] = trace.as_metadata()
        reranked.append(
            candidate.__class__(
                chunk_id=candidate.chunk_id,
                organization_id=candidate.organization_id,
                document_record_id=candidate.document_record_id,
                document_version_id=candidate.document_version_id,
                collection_id=candidate.collection_id,
                chunk_key=candidate.chunk_key,
                text=candidate.text,
                source=candidate.source,
                score=trace.final_score,
                content_hash=candidate.content_hash,
                metadata=metadata,
                classification=candidate.classification,
            )
        )

    return tuple(
        sorted(
            reranked,
            key=lambda item: (
                item.score,
                _safe_float(((item.metadata or {}).get("rerank") or {}).get("original_score")),
                str(item.chunk_id),
            ),
            reverse=True,
        )
    )


def rerank_metrics(candidates: tuple, *, stage: str) -> dict[str, object]:
    scores = []
    for candidate in candidates:
        trace = (candidate.metadata or {}).get("rerank") or {}
        if trace:
            scores.append(_safe_float(trace.get("rerank_score")))

    return {
        "reranking_enabled": True,
        "reranking_mode": "rules",
        "reranker": "deterministic_rules_v1",
        f"{stage}_reranked_count": len(scores),
        f"{stage}_rerank_score_total": round(sum(scores), 6),
    }


def _score_candidate(candidate: Any, normalized: QueryNormalizationResult) -> RuleRerankTrace:
    original_score = _safe_float(getattr(candidate, "score", 0.0))
    text = str(getattr(candidate, "text", "") or "")
    text_lower = text.lower()
    metadata = getattr(candidate, "metadata", None) or {}

    rules: dict[str, float] = {}

    phrase_bonus = _phrase_bonus(text_lower, normalized)
    if phrase_bonus:
        rules["quoted_phrase_match_bonus"] = phrase_bonus

    identifier_bonus = _identifier_bonus(text_lower, normalized)
    if identifier_bonus:
        rules["technical_identifier_match_bonus"] = identifier_bonus

    term_bonus = _term_bonus(text_lower, normalized)
    if term_bonus:
        rules["query_term_coverage_bonus"] = term_bonus

    highlight_bonus = _highlight_bonus(metadata)
    if highlight_bonus:
        rules["highlight_match_bonus"] = highlight_bonus

    quality_bonus = _quality_bonus(metadata)
    if quality_bonus:
        rules["quality_signal_bonus"] = quality_bonus

    noise_penalty = _noise_penalty(text, metadata)
    if noise_penalty:
        rules["noise_penalty"] = noise_penalty

    rerank_score = round(sum(rules.values()), 6)
    final_score = round(max(0.0, original_score + rerank_score), 6)
    return RuleRerankTrace(
        original_score=original_score,
        rerank_score=rerank_score,
        final_score=final_score,
        rules=rules,
    )


def _phrase_bonus(text_lower: str, normalized: QueryNormalizationResult) -> float:
    score = 0.0
    for phrase in normalized.quoted_phrases:
        value = phrase.strip().lower()
        if value and value in text_lower:
            score += 0.2
    return round(score, 6)


def _identifier_bonus(text_lower: str, normalized: QueryNormalizationResult) -> float:
    score = 0.0
    for identifier in normalized.technical_identifiers:
        value = identifier.strip().lower()
        if value and value in text_lower:
            score += 0.1
    return round(score, 6)


def _term_bonus(text_lower: str, normalized: QueryNormalizationResult) -> float:
    terms = [term.lower() for term in normalized.normalized_query_text.split() if len(term) >= 3]
    if not terms:
        return 0.0

    matched = sum(1 for term in terms if term in text_lower)
    coverage = matched / max(1, len(terms))
    return round(coverage * 0.15, 6)


def _highlight_bonus(metadata: dict[str, Any]) -> float:
    highlight = metadata.get("highlight") or {}
    try:
        match_count = int(highlight.get("match_count") or 0)
    except Exception:
        match_count = 0
    return round(min(match_count, 5) * 0.03, 6)


def _quality_bonus(metadata: dict[str, Any]) -> float:
    quality = metadata.get("quality") or {}
    if not isinstance(quality, dict):
        return 0.0

    score = 0.0
    if quality.get("smoke") is True:
        score += 0.03
    if quality.get("accepted") is True:
        score += 0.05
    if quality.get("validated") is True:
        score += 0.05
    return round(score, 6)


def _noise_penalty(text: str, metadata: dict[str, Any]) -> float:
    penalty = 0.0
    if len(text.strip()) < 40:
        penalty -= 0.05

    quality = metadata.get("quality") or {}
    if isinstance(quality, dict):
        if quality.get("low_value") is True:
            penalty -= 0.1
        if quality.get("noise") is True:
            penalty -= 0.15

    return round(penalty, 6)


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0
