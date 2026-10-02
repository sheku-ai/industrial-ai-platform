"""Extractive answer builder for Knowledge Runtime.

Sprint 11.5 adds answer-like output without generation.

Design constraints:
- no LLM dependency;
- no synthesis beyond extracted evidence;
- no vector dependency;
- answer must remain citation-backed;
- answer_generated must remain false.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.retrieval.query_normalization import QueryNormalizationResult

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class ExtractiveEvidence:
    """Evidence sentence selected from a context item."""

    citation_key: str
    chunk_id: str
    text: str
    score: float
    matched_terms: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, object]:
        return {
            "citation_key": self.citation_key,
            "chunk_id": self.chunk_id,
            "text": self.text,
            "score": self.score,
            "matched_terms": list(self.matched_terms),
        }


@dataclass(frozen=True)
class ExtractiveAnswer:
    """Answer assembled only from retrieved context evidence."""

    answer: str | None
    evidence: tuple[ExtractiveEvidence, ...] = field(default_factory=tuple)

    def metrics(self) -> dict[str, object]:
        return {
            "extractive_answer_enabled": True,
            "extractive_evidence_count": len(self.evidence),
            "extractive_builder": "deterministic_extractive_v1",
        }


def build_extractive_answer(
    context_items: tuple, normalized: QueryNormalizationResult, max_evidence: int = 3
) -> ExtractiveAnswer:
    """Build a citation-backed extractive answer from selected context items."""

    evidence: list[ExtractiveEvidence] = []
    terms = _query_terms(normalized)

    for item in context_items:
        selected = _select_sentence(item.text, terms)
        if not selected:
            continue
        sentence, matched = selected
        evidence.append(
            ExtractiveEvidence(
                citation_key=item.citation_key or "",
                chunk_id=str(item.chunk_id),
                text=sentence,
                score=float(item.score or 0.0),
                matched_terms=matched,
            )
        )
        if len(evidence) >= max_evidence:
            break

    if not evidence:
        return ExtractiveAnswer(answer=None, evidence=())

    lines = []
    for item in evidence:
        citation = f" [{item.citation_key}]" if item.citation_key else ""
        lines.append(f"- {item.text}{citation}")

    return ExtractiveAnswer(answer="\n".join(lines), evidence=tuple(evidence))


def evidence_as_metrics(answer: ExtractiveAnswer) -> dict[str, object]:
    return {
        **answer.metrics(),
        "extractive_evidence": [item.as_dict() for item in answer.evidence],
    }


def _query_terms(normalized: QueryNormalizationResult) -> tuple[str, ...]:
    terms: list[str] = []
    terms.extend(normalized.quoted_phrases)
    terms.extend(normalized.technical_identifiers)
    terms.extend(term for term in normalized.normalized_query_text.split() if len(term) >= 3)
    return tuple(dict.fromkeys(term.strip() for term in terms if term.strip()))


def _select_sentence(text: str, terms: tuple[str, ...]) -> tuple[str, tuple[str, ...]] | None:
    raw = str(text or "").strip()
    if not raw:
        return None

    sentences = [sentence.strip() for sentence in _SENTENCE_RE.split(raw) if sentence.strip()]
    if not sentences:
        sentences = [raw]

    best_sentence = ""
    best_matches: tuple[str, ...] = ()
    best_score = -1

    for sentence in sentences:
        matched = tuple(term for term in terms if term.lower() in sentence.lower())
        score = len(matched)
        if score > best_score:
            best_sentence = sentence
            best_matches = matched
            best_score = score

    if not best_sentence:
        return None

    return _trim(best_sentence), best_matches


def _trim(text: str, max_chars: int = 500) -> str:
    value = " ".join(text.split())
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1].rstrip() + "…"
