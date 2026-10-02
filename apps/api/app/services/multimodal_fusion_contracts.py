from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

FUSION_SCHEMA = "multimodal-fusion-record/v1"


class ContentModality(StrEnum):
    TEXT = "text"
    OCR_TEXT = "ocr_text"
    VISUAL_DESCRIPTION = "visual_description"


class EvidenceRole(StrEnum):
    AUTHORITATIVE = "authoritative"
    DERIVED = "derived"


class CitationBasis(StrEnum):
    SOURCE_TEXT = "source_text"
    SOURCE_VISUAL = "source_visual"
    DERIVED_VISUAL_DESCRIPTION = "derived_visual_description"


def fuse_knowledge_record(
    record: Mapping[str, Any],
    *,
    fusion_order: int,
) -> dict[str, Any]:
    """Add governed multimodal fields without removing source record fields."""
    if not isinstance(record, Mapping):
        raise TypeError("knowledge record must be a mapping")
    fused = dict(record)
    metadata = dict(fused.get("metadata") or {})
    modality = _modality(metadata)
    role = _role(modality, metadata)

    metadata.update(
        fusion_schema=FUSION_SCHEMA,
        fusion_order=fusion_order,
        evidence_role=role.value,
        authoritative=role == EvidenceRole.AUTHORITATIVE,
        derived_content=role == EvidenceRole.DERIVED,
        citation_basis=_citation_basis(modality, role).value,
        source_locator=_source_locator(metadata),
    )
    fused["metadata"] = metadata
    return fused


def _modality(metadata: Mapping[str, Any]) -> ContentModality:
    value = str(metadata.get("content_modality") or ContentModality.TEXT.value)
    try:
        return ContentModality(value)
    except ValueError:
        return ContentModality.TEXT


def _role(modality: ContentModality, metadata: Mapping[str, Any]) -> EvidenceRole:
    if metadata.get("derived_content") is True:
        return EvidenceRole.DERIVED
    if modality == ContentModality.VISUAL_DESCRIPTION:
        return EvidenceRole.DERIVED
    return EvidenceRole.AUTHORITATIVE


def _citation_basis(modality: ContentModality, role: EvidenceRole) -> CitationBasis:
    if modality == ContentModality.VISUAL_DESCRIPTION and role == EvidenceRole.DERIVED:
        return CitationBasis.DERIVED_VISUAL_DESCRIPTION
    if modality == ContentModality.VISUAL_DESCRIPTION:
        return CitationBasis.SOURCE_VISUAL
    return CitationBasis.SOURCE_TEXT


def _source_locator(metadata: Mapping[str, Any]) -> dict[str, Any]:
    locator = metadata.get("source_locator")
    if isinstance(locator, Mapping):
        return dict(locator)
    provenance = metadata.get("provenance")
    if isinstance(provenance, Mapping):
        return dict(provenance)
    section_ref = metadata.get("section_ref")
    if isinstance(section_ref, Mapping):
        return dict(section_ref)
    return {}
