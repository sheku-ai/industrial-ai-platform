"""Deterministic query normalization for Search Quality Runtime.

Sprint 11.1 introduces CPU-first query normalization before PostgreSQL FTS.

Design constraints:
- no LLM dependency;
- no embedding or reranking dependency;
- no customer-specific terminology;
- preserve quoted phrases and technical identifiers;
- keep normalization explainable through response metrics.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WHITESPACE_RE = re.compile(r"\s+")
_SPACE_AROUND_QUOTES_RE = re.compile(r'\s*"\s*')
_SPACE_AROUND_PUNCT_RE = re.compile(r"\s+([,.;:!?])")

_SMART_QUOTE_MAP = str.maketrans(
    {
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "―": "-",
    }
)


@dataclass(frozen=True)
class QueryNormalizationResult:
    """Normalized query plus explainable trace."""

    original_query_text: str
    normalized_query_text: str
    changed: bool
    applied_rules: tuple[str, ...] = field(default_factory=tuple)
    quoted_phrases: tuple[str, ...] = field(default_factory=tuple)
    technical_identifiers: tuple[str, ...] = field(default_factory=tuple)

    def as_metrics(self) -> dict[str, object]:
        return {
            "query_normalized": True,
            "query_changed": self.changed,
            "original_query_text": self.original_query_text,
            "normalized_query_text": self.normalized_query_text,
            "query_normalization_rules": list(self.applied_rules),
            "quoted_phrase_count": len(self.quoted_phrases),
            "technical_identifier_count": len(self.technical_identifiers),
        }


def _extract_quoted_phrases(text: str) -> tuple[str, ...]:
    phrases = [match.strip() for match in re.findall(r'"([^"\n]{1,256})"', text)]
    return tuple(dict.fromkeys(phrase for phrase in phrases if phrase))


def _extract_technical_identifiers(text: str) -> tuple[str, ...]:
    """Detect generic identifiers that should not be rewritten.

    This intentionally avoids domain-specific vocabularies. It only captures
    structural forms commonly used across technical documents.
    """

    patterns = [
        r"\b[A-Z]{2,12}\b",
        r"\b[A-Za-z]{1,12}[-_/][A-Za-z0-9][A-Za-z0-9._/-]{1,64}\b",
        r"\b\d+(?:\.\d+){1,6}\b",
        r"\b[A-Za-z]+\d+[A-Za-z0-9._/-]*\b",
    ]

    identifiers: list[str] = []
    for pattern in patterns:
        identifiers.extend(re.findall(pattern, text))

    return tuple(dict.fromkeys(item for item in identifiers if item))


def normalize_query_text(query_text: str) -> QueryNormalizationResult:
    """Normalize a user query for deterministic PostgreSQL FTS execution."""

    original = "" if query_text is None else str(query_text)
    current = original
    rules: list[str] = []

    normalized_unicode = unicodedata.normalize("NFKC", current)
    if normalized_unicode != current:
        current = normalized_unicode
        rules.append("unicode_nfkc")

    translated = current.translate(_SMART_QUOTE_MAP)
    if translated != current:
        current = translated
        rules.append("smart_punctuation_normalized")

    without_control = _CONTROL_CHARS_RE.sub(" ", current)
    if without_control != current:
        current = without_control
        rules.append("control_characters_removed")

    compact_whitespace = _WHITESPACE_RE.sub(" ", current).strip()
    if compact_whitespace != current:
        current = compact_whitespace
        rules.append("whitespace_compacted")

    # Preserve phrase semantics while removing accidental spaces inside quotes.
    quote_normalized = _SPACE_AROUND_QUOTES_RE.sub('"', current)
    if quote_normalized != current:
        current = quote_normalized
        rules.append("quote_spacing_normalized")

    punctuation_normalized = _SPACE_AROUND_PUNCT_RE.sub(r"\1", current)
    if punctuation_normalized != current:
        current = punctuation_normalized
        rules.append("punctuation_spacing_normalized")

    # Do not lowercase globally. PostgreSQL FTS is case-insensitive for the
    # current simple configuration, and preserving user-visible identifiers keeps
    # traceability safer for technical searches.
    if not current:
        current = original.strip()

    return QueryNormalizationResult(
        original_query_text=original,
        normalized_query_text=current,
        changed=current != original,
        applied_rules=tuple(rules),
        quoted_phrases=_extract_quoted_phrases(current),
        technical_identifiers=_extract_technical_identifiers(current),
    )
