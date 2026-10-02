from __future__ import annotations

import json
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True)
class DeterministicChunkIdentity:
    chunk_key: str
    content_hash: str


def _normalize_string(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _normalize_metadata_value(value: str | int | float | bool | None):
    if isinstance(value, str):
        return _normalize_string(value)
    return value


def build_deterministic_chunk_identity(
    *,
    normalized_text: str,
    structural_path: Sequence[str] | None = None,
    metadata: Mapping[str, str | int | float | bool | None] | None = None,
) -> DeterministicChunkIdentity:
    unicode_normalized_text = _normalize_string(normalized_text)
    canonical_text = "\n".join(line.rstrip() for line in unicode_normalized_text.strip().splitlines())
    content_hash = sha256(canonical_text.encode("utf-8")).hexdigest()

    path = [
        _normalize_string(part).strip() for part in (structural_path or ()) if part and _normalize_string(part).strip()
    ]
    metadata_payload = {
        _normalize_string(str(key)): _normalize_metadata_value((metadata or {})[key])
        for key in sorted(metadata or {}, key=lambda item: _normalize_string(str(item)))
    }
    payload = json.dumps(
        {"path": path, "metadata": metadata_payload, "content_hash": content_hash},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    identity_hash = sha256(payload.encode("utf-8")).hexdigest()
    prefix = "/".join(path[:4]) or "content"
    return DeterministicChunkIdentity(
        chunk_key=f"{prefix}:{identity_hash}",
        content_hash=content_hash,
    )
