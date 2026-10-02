"""Deterministic search highlighting for Knowledge Runtime.

Sprint 11.2 adds CPU-first snippets for PostgreSQL FTS results.

Design constraints:
- no LLM dependency;
- no vector dependency;
- no customer-specific taxonomy;
- no database schema change;
- highlights are derived from persisted chunk text only.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

from app.services.retrieval.query_normalization import QueryNormalizationResult

_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9._:/-]{1,80}")

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "de",
    "del",
    "el",
    "en",
    "for",
    "from",
    "is",
    "la",
    "las",
    "los",
    "of",
    "on",
    "or",
    "para",
    "por",
    "the",
    "to",
    "un",
    "una",
    "with",
    "y",
}


@dataclass(frozen=True)
class HighlightResult:
    """Snippet and match trace for a candidate chunk."""

    snippet: str
    matched_terms: tuple[str, ...] = field(default_factory=tuple)
    match_count: int = 0
    window_start: int = 0
    window_end: int = 0

    def as_metadata(self) -> dict[str, object]:
        return {
            "snippet": self.snippet,
            "matched_terms": list(self.matched_terms),
            "match_count": self.match_count,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "highlighter": "deterministic_cpu_v1",
        }


def _query_terms(normalized: QueryNormalizationResult) -> tuple[str, ...]:
    terms: list[str] = []
    for phrase in normalized.quoted_phrases:
        phrase = phrase.strip()
        if phrase:
            terms.append(phrase)

    for identifier in normalized.technical_identifiers:
        if identifier:
            terms.append(identifier)

    for token in _TOKEN_RE.findall(normalized.normalized_query_text):
        value = token.strip()
        if len(value) < 3:
            continue
        if value.lower() in _STOPWORDS:
            continue
        terms.append(value)

    return tuple(dict.fromkeys(terms))


def _find_first_match(text: str, terms: tuple[str, ...]) -> tuple[int, str] | None:
    text_lower = text.lower()
    best: tuple[int, str] | None = None

    for term in terms:
        pos = text_lower.find(term.lower())
        if pos < 0:
            continue
        if best is None or pos < best[0]:
            best = (pos, term)

    return best


def _window(text: str, center: int, window_chars: int) -> tuple[int, int]:
    half = max(40, window_chars // 2)
    start = max(0, center - half)
    end = min(len(text), start + window_chars)
    start = max(0, end - window_chars)
    return start, end


def _highlight_html(snippet: str, terms: tuple[str, ...]) -> tuple[str, tuple[str, ...], int]:
    escaped = html.escape(snippet)
    matched: list[str] = []
    match_count = 0

    # Longer terms first so phrases/identifiers win over subterms.
    ordered = sorted(terms, key=len, reverse=True)

    for _index, term in enumerate(ordered):
        escaped_term = html.escape(term)
        if not escaped_term:
            continue

        pattern = re.compile(re.escape(escaped_term), re.IGNORECASE)

        def repl(match: re.Match[str], matched_term: str = term) -> str:
            nonlocal match_count
            match_count += 1
            matched.append(matched_term)
            return f"<mark>{match.group(0)}</mark>"

        escaped = pattern.sub(repl, escaped)

    unique_matched = tuple(dict.fromkeys(matched))
    return escaped, unique_matched, match_count


def build_highlight(text: str, normalized: QueryNormalizationResult, window_chars: int = 320) -> HighlightResult:
    """Build a deterministic snippet for a chunk using normalized query terms."""

    raw = "" if text is None else str(text)
    if not raw:
        return HighlightResult(snippet="", window_start=0, window_end=0)

    terms = _query_terms(normalized)
    first = _find_first_match(raw, terms) if terms else None

    if first is None:
        start, end = 0, min(len(raw), window_chars)
    else:
        start, end = _window(raw, first[0], window_chars)

    snippet_text = raw[start:end].strip()
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(raw) else ""
    highlighted, matched_terms, match_count = _highlight_html(snippet_text, terms)

    return HighlightResult(
        snippet=f"{prefix}{highlighted}{suffix}",
        matched_terms=matched_terms,
        match_count=match_count,
        window_start=start,
        window_end=end,
    )
