from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

COMMUNITY_INTENT_PROVIDER = "community.setfit"
COMMUNITY_INTENT_MODEL_FAMILY = "conversation_intent"
COMMUNITY_INTENT_MODEL_VERSION = "community-intent-v1"
COMMUNITY_INTENT_DATASET_VERSION = "community-intent-dataset-v1"
COMMUNITY_INTENT_BASE_MODEL = "intfloat/multilingual-e5-small"
COMMUNITY_INTENT_ARTIFACT_REFERENCE = "runtime/intent-models/community-intent-v1"
COMMUNITY_INTENT_MANIFEST_NAME = "sheku-intent-model.json"
COMMUNITY_INTENT_LANGUAGES = ("es", "en")
COMMUNITY_INTENT_CATALOG = (
    "knowledge_query",
    "contextual_follow_up",
    "new_topic",
    "response_refinement",
    "citation_request",
    "conversation_summary",
    "non_knowledge_interaction",
)
MINIMUM_EXAMPLES_PER_INTENT = 30

_ARTIFACT_EXCLUDED_DIRECTORIES = frozenset({".cache", "__pycache__"})
_ARTIFACT_EXCLUDED_FILES = frozenset(
    {
        ".DS_Store",
        ".gitkeep",
        COMMUNITY_INTENT_MANIFEST_NAME,
    }
)
_ARTIFACT_EXCLUDED_SUFFIXES = (".lock", ".tmp")
_EXPECTED_ARTIFACT_FILES = (
    "config.json",
    "config_setfit.json",
    "model_head.pkl",
    "modules.json",
    "tokenizer_config.json",
)
_EXPECTED_WEIGHT_FILES = ("model.safetensors", "pytorch_model.bin")
_EXPECTED_TOKENIZER_FILES = ("tokenizer.json", "sentencepiece.bpe.model", "vocab.txt")


@dataclass(frozen=True)
class IntentTrainingExample:
    text: str
    label: str
    language: str


@dataclass(frozen=True)
class DatasetStatistics:
    example_count: int
    per_label_counts: dict[str, int]
    per_language_counts: dict[str, int]


def canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _is_sha256_digest(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        bytes.fromhex(value)
    except ValueError:
        return False
    return True


def normalize_intent_text(text: str) -> str:
    return " ".join(str(text or "").split())


def prepare_e5_classification_text(text: str) -> str:
    normalized = normalize_intent_text(text)
    if not normalized:
        raise ValueError("intent classification text must not be empty")
    if normalized.casefold().startswith("query:"):
        content = normalized.partition(":")[2].strip()
        if not content:
            raise ValueError("intent classification text must not be empty")
        return f"query: {content}"
    return f"query: {normalized}"


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON payload must be an object: {path}")
    return value


def load_training_dataset(
    path: Path,
    *,
    minimum_examples_per_intent: int = MINIMUM_EXAMPLES_PER_INTENT,
) -> tuple[IntentTrainingExample, ...]:
    examples: list[IntentTrainingExample] = []
    duplicate_texts: set[str] = set()
    seen_texts: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"intent dataset is unavailable: {path}") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid dataset JSON at line {line_number}") from exc
        if not isinstance(item, dict):
            raise ValueError(f"dataset line {line_number} must be an object")
        text = normalize_intent_text(item.get("text"))
        label = item.get("label")
        language = item.get("language")
        if not text:
            raise ValueError(f"dataset line {line_number} has empty text")
        if label not in COMMUNITY_INTENT_CATALOG:
            raise ValueError(f"dataset line {line_number} has unsupported label: {label!r}")
        if language not in COMMUNITY_INTENT_LANGUAGES:
            raise ValueError(f"dataset line {line_number} has unsupported language: {language!r}")
        if text in seen_texts:
            duplicate_texts.add(text)
        seen_texts.add(text)
        examples.append(IntentTrainingExample(text=text, label=label, language=language))
    if duplicate_texts:
        raise ValueError(f"dataset contains exact duplicate text: {sorted(duplicate_texts)[0]!r}")
    statistics = dataset_statistics(examples)
    if set(statistics.per_label_counts) != set(COMMUNITY_INTENT_CATALOG):
        raise ValueError("dataset must contain exactly the seven Community intent labels")
    if set(statistics.per_language_counts) != set(COMMUNITY_INTENT_LANGUAGES):
        raise ValueError("dataset must contain both es and en examples")
    below_minimum = {
        label: count
        for label, count in statistics.per_label_counts.items()
        if count < minimum_examples_per_intent
    }
    if below_minimum:
        raise ValueError(f"dataset has insufficient examples per intent: {below_minimum}")
    return tuple(examples)


def dataset_statistics(examples: Iterable[IntentTrainingExample]) -> DatasetStatistics:
    materialized = tuple(examples)
    per_label = Counter(example.label for example in materialized)
    per_language = Counter(example.language for example in materialized)
    return DatasetStatistics(
        example_count=len(materialized),
        per_label_counts={label: per_label[label] for label in COMMUNITY_INTENT_CATALOG if per_label[label]},
        per_language_counts={language: per_language[language] for language in COMMUNITY_INTENT_LANGUAGES if per_language[language]},
    )


def dataset_hash(examples: Iterable[IntentTrainingExample], *, dataset_version: str) -> str:
    canonical_examples = sorted(
        (
            {
                "text": example.text,
                "label": example.label,
                "language": example.language,
            }
            for example in examples
        ),
        key=lambda item: (item["label"], item["language"], item["text"]),
    )
    return canonical_hash(
        {
            "dataset_version": dataset_version,
            "examples": canonical_examples,
        }
    )


def load_and_validate_dataset_manifest(
    path: Path,
    *,
    examples: Iterable[IntentTrainingExample],
) -> dict[str, Any]:
    manifest = _load_json_object(path)
    statistics = dataset_statistics(examples)
    expected = {
        "dataset_version": COMMUNITY_INTENT_DATASET_VERSION,
        "target_model_version": COMMUNITY_INTENT_MODEL_VERSION,
        "intent_catalog": list(COMMUNITY_INTENT_CATALOG),
        "languages": list(COMMUNITY_INTENT_LANGUAGES),
        "example_count": statistics.example_count,
        "per_label_counts": statistics.per_label_counts,
        "per_language_counts": statistics.per_language_counts,
    }
    if manifest != expected:
        raise ValueError("dataset manifest does not match the canonical dataset statistics")
    return manifest


def load_training_configuration(path: Path) -> dict[str, Any]:
    configuration = _load_json_object(path)
    expected_identity = {
        "model_family": COMMUNITY_INTENT_MODEL_FAMILY,
        "provider": COMMUNITY_INTENT_PROVIDER,
        "model_version": COMMUNITY_INTENT_MODEL_VERSION,
        "dataset_version": COMMUNITY_INTENT_DATASET_VERSION,
        "base_model": COMMUNITY_INTENT_BASE_MODEL,
    }
    for field_name, expected_value in expected_identity.items():
        if configuration.get(field_name) != expected_value:
            raise ValueError(f"training configuration {field_name} must be {expected_value!r}")
    random_seed = configuration.get("random_seed")
    if not isinstance(random_seed, int) or isinstance(random_seed, bool) or random_seed < 0:
        raise ValueError("training configuration random_seed must be a non-negative integer")
    input_preparation = configuration.get("input_preparation")
    if input_preparation != {
        "strategy": "e5_query_prefix",
        "prefix": "query: ",
        "whitespace_normalization": "collapse",
    }:
        raise ValueError("training configuration must use the canonical E5 query input preparation")
    training_parameters = configuration.get("training_parameters")
    if not isinstance(training_parameters, dict) or not training_parameters:
        raise ValueError("training configuration parameters must be a non-empty object")
    if not isinstance(training_parameters.get("checkpoint_directory"), str):
        raise ValueError("training configuration checkpoint_directory must be relative")
    checkpoint_directory = Path(training_parameters["checkpoint_directory"])
    if checkpoint_directory.is_absolute() or ".." in checkpoint_directory.parts:
        raise ValueError("training configuration checkpoint_directory must be relative")
    return configuration


def effective_build_configuration(
    configuration: dict[str, Any],
    *,
    base_model_override: str | None = None,
) -> dict[str, Any]:
    base_model = normalize_intent_text(base_model_override or configuration["base_model"])
    if not base_model:
        raise ValueError("build base model must not be empty")
    return {
        **configuration,
        "base_model": base_model,
        "training_parameters": dict(configuration["training_parameters"]),
        "input_preparation": dict(configuration["input_preparation"]),
    }


def build_configuration_hash(configuration: dict[str, Any]) -> str:
    return canonical_hash(configuration)


def _artifact_files(artifact_directory: Path) -> tuple[Path, ...]:
    if not artifact_directory.is_dir():
        raise ValueError(f"intent model artifact directory is unavailable: {artifact_directory}")
    files = []
    for path in artifact_directory.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(artifact_directory)
        if any(part in _ARTIFACT_EXCLUDED_DIRECTORIES for part in relative.parts):
            continue
        if path.name in _ARTIFACT_EXCLUDED_FILES or path.name.endswith(_ARTIFACT_EXCLUDED_SUFFIXES):
            continue
        files.append(path)
    return tuple(sorted(files, key=lambda item: item.relative_to(artifact_directory).as_posix()))


def verify_setfit_artifact(artifact_directory: Path) -> None:
    available = {
        path.relative_to(artifact_directory).as_posix()
        for path in _artifact_files(artifact_directory)
    }
    missing = [name for name in _EXPECTED_ARTIFACT_FILES if name not in available]
    if missing:
        raise ValueError(f"SetFit artifact is incomplete; missing files: {missing}")
    if not any(name in available for name in _EXPECTED_WEIGHT_FILES):
        raise ValueError("SetFit artifact is incomplete; model weights are unavailable")
    if all(name in available for name in _EXPECTED_WEIGHT_FILES):
        raise ValueError("SetFit artifact contains duplicate model weight formats")
    if not any(name in available for name in _EXPECTED_TOKENIZER_FILES):
        raise ValueError("SetFit artifact is incomplete; tokenizer data is unavailable")


def artifact_hash(artifact_directory: Path) -> str:
    entries = []
    for path in _artifact_files(artifact_directory):
        content = path.read_bytes()
        entries.append(
            {
                "path": path.relative_to(artifact_directory).as_posix(),
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    if not entries:
        raise ValueError("intent model artifact contains no identity-bearing files")
    return canonical_hash({"files": entries})


def build_artifact_manifest(
    *,
    artifact_digest: str,
    dataset_digest: str,
    build_configuration_digest: str,
    base_model: str,
) -> dict[str, Any]:
    return {
        "model_family": COMMUNITY_INTENT_MODEL_FAMILY,
        "provider": COMMUNITY_INTENT_PROVIDER,
        "model_version": COMMUNITY_INTENT_MODEL_VERSION,
        "dataset_version": COMMUNITY_INTENT_DATASET_VERSION,
        "base_model": base_model,
        "artifact_reference": COMMUNITY_INTENT_ARTIFACT_REFERENCE,
        "intent_catalog": list(COMMUNITY_INTENT_CATALOG),
        "languages": list(COMMUNITY_INTENT_LANGUAGES),
        "artifact_hash": artifact_digest,
        "dataset_hash": dataset_digest,
        "build_configuration_hash": build_configuration_digest,
        "offline_runtime": True,
    }


def write_artifact_manifest(artifact_directory: Path, manifest: dict[str, Any]) -> Path:
    destination = artifact_directory / COMMUNITY_INTENT_MANIFEST_NAME
    destination.write_bytes(canonical_json_bytes(manifest) + b"\n")
    return destination


def load_and_validate_artifact_manifest(path: Path) -> dict[str, Any]:
    manifest = _load_json_object(path)
    expected = {
        "model_family": COMMUNITY_INTENT_MODEL_FAMILY,
        "provider": COMMUNITY_INTENT_PROVIDER,
        "model_version": COMMUNITY_INTENT_MODEL_VERSION,
        "dataset_version": COMMUNITY_INTENT_DATASET_VERSION,
        "base_model": COMMUNITY_INTENT_BASE_MODEL,
        "artifact_reference": COMMUNITY_INTENT_ARTIFACT_REFERENCE,
        "intent_catalog": list(COMMUNITY_INTENT_CATALOG),
        "languages": list(COMMUNITY_INTENT_LANGUAGES),
        "offline_runtime": True,
    }
    for field_name, expected_value in expected.items():
        if manifest.get(field_name) != expected_value:
            raise ValueError(f"artifact manifest {field_name} must be {expected_value!r}")
    for field_name in ("artifact_hash", "dataset_hash", "build_configuration_hash"):
        value = manifest.get(field_name)
        if not _is_sha256_digest(value):
            raise ValueError(f"artifact manifest {field_name} must be a SHA-256 digest")
    return manifest
