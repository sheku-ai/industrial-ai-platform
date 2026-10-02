from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.community_intent_model_artifact import (
    COMMUNITY_INTENT_CATALOG,
    COMMUNITY_INTENT_DATASET_VERSION,
    COMMUNITY_INTENT_LANGUAGES,
    MINIMUM_EXAMPLES_PER_INTENT,
    dataset_hash,
    dataset_statistics,
    load_and_validate_dataset_manifest,
    load_training_dataset,
)

RESOURCE_ROOT = Path("apps/api/resources/intent-models/community-intent-v1")
CALIBRATION_COVERAGE = (
    ("new_topic", "es", ("cambiemos", "tema")),
    ("new_topic", "en", ("change", "subject")),
    ("knowledge_query", "es", ("política", "aprobaciones")),
    ("knowledge_query", "en", ("policy", "approvals")),
    ("contextual_follow_up", "es", ("quién", "lo")),
    ("contextual_follow_up", "en", ("who", "it")),
    ("response_refinement", "es", ("respuesta", "anterior")),
    ("response_refinement", "en", ("previous", "answer")),
)


def test_seed_dataset_matches_balanced_bilingual_manifest() -> None:
    examples = load_training_dataset(RESOURCE_ROOT / "training.jsonl")
    manifest = load_and_validate_dataset_manifest(
        RESOURCE_ROOT / "dataset-manifest.json",
        examples=examples,
    )
    statistics = dataset_statistics(examples)

    assert set(example.label for example in examples) == set(COMMUNITY_INTENT_CATALOG)
    assert set(example.language for example in examples) == set(COMMUNITY_INTENT_LANGUAGES)
    assert all(statistics.per_label_counts[label] >= MINIMUM_EXAMPLES_PER_INTENT for label in COMMUNITY_INTENT_CATALOG)
    assert manifest["example_count"] == statistics.example_count
    assert manifest["per_label_counts"] == statistics.per_label_counts
    assert manifest["per_language_counts"] == statistics.per_language_counts


def test_dataset_hash_is_deterministic_and_order_independent() -> None:
    examples = load_training_dataset(RESOURCE_ROOT / "training.jsonl")

    first = dataset_hash(examples, dataset_version=COMMUNITY_INTENT_DATASET_VERSION)
    second = dataset_hash(reversed(examples), dataset_version=COMMUNITY_INTENT_DATASET_VERSION)

    assert first == second
    assert len(first) == 64


def test_seed_dataset_preserves_critical_calibration_coverage() -> None:
    examples = load_training_dataset(RESOURCE_ROOT / "training.jsonl")

    for label, language, semantic_markers in CALIBRATION_COVERAGE:
        matching_texts = (
            example.text.casefold() for example in examples if example.label == label and example.language == language
        )
        assert any(all(marker.casefold() in text for marker in semantic_markers) for text in matching_texts), (
            f"missing {language} calibration coverage for {label}"
        )


def _write_jsonl(path: Path, rows: list[dict[str, str]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ({"text": "", "label": "knowledge_query", "language": "es"}, "empty text"),
        (
            {"text": "hello", "label": "unsupported", "language": "en"},
            "unsupported label",
        ),
        (
            {"text": "bonjour", "label": "knowledge_query", "language": "fr"},
            "unsupported language",
        ),
    ],
)
def test_dataset_rejects_invalid_examples(tmp_path: Path, row: dict[str, str], message: str) -> None:
    dataset = tmp_path / "invalid.jsonl"
    _write_jsonl(dataset, [row])

    with pytest.raises(ValueError, match=message):
        load_training_dataset(dataset)


def test_dataset_rejects_exact_duplicate_text(tmp_path: Path) -> None:
    dataset = tmp_path / "duplicate.jsonl"
    row = {"text": "same text", "label": "knowledge_query", "language": "en"}
    _write_jsonl(dataset, [row, row])

    with pytest.raises(ValueError, match="exact duplicate"):
        load_training_dataset(dataset)
