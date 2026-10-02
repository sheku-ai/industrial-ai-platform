#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import random
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPOSITORY_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.services.community_intent_model_artifact import (  # noqa: E402
    COMMUNITY_INTENT_ARTIFACT_REFERENCE,
    COMMUNITY_INTENT_BASE_MODEL,
    COMMUNITY_INTENT_CATALOG,
    COMMUNITY_INTENT_DATASET_VERSION,
    artifact_hash,
    build_artifact_manifest,
    build_configuration_hash,
    dataset_hash,
    effective_build_configuration,
    load_and_validate_dataset_manifest,
    load_training_configuration,
    load_training_dataset,
    prepare_e5_classification_text,
    verify_setfit_artifact,
    write_artifact_manifest,
)

DEFAULT_DATASET = API_ROOT / "resources" / "intent-models" / "community-intent-v1" / "training.jsonl"
DEFAULT_DATASET_MANIFEST = (
    API_ROOT / "resources" / "intent-models" / "community-intent-v1" / "dataset-manifest.json"
)
DEFAULT_CONFIG = API_ROOT / "resources" / "intent-models" / "community-intent-v1" / "training-config.json"
DEFAULT_OUTPUT = API_ROOT / COMMUNITY_INTENT_ARTIFACT_REFERENCE
BUILD_REQUIREMENTS = "apps/api/requirements-intent-build.txt"
BUILD_DEPENDENCIES = (
    ("datasets", "datasets"),
    ("numpy", "numpy"),
    ("scikit-learn", "sklearn"),
    ("sentence-transformers", "sentence_transformers"),
    ("setfit", "setfit"),
    ("torch", "torch"),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the SHEKU Community SetFit intent model artifact explicitly.",
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--dataset-manifest", type=Path, default=DEFAULT_DATASET_MANIFEST)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--base-model",
        help=(
            "Build-only encoder override for future experiments. The official "
            "community-intent-v1 output requires intfloat/multilingual-e5-small."
        ),
    )
    return parser


def _missing_build_dependency_error(dependencies: list[str]) -> RuntimeError:
    missing = ", ".join(sorted(dependencies))
    return RuntimeError(
        f"Community intent model build dependencies are missing: {missing}. "
        f"Install them with: apps/api/.venv/bin/pip install -r {BUILD_REQUIREMENTS}"
    )


def _validate_build_dependencies() -> None:
    missing = [
        distribution
        for distribution, module in BUILD_DEPENDENCIES
        if importlib.util.find_spec(module) is None
    ]
    if missing:
        raise _missing_build_dependency_error(missing)


def _set_random_seeds(seed: int) -> None:
    random.seed(seed)
    try:
        import numpy as np
        import torch
    except ModuleNotFoundError as exc:
        raise _missing_build_dependency_error([exc.name or "unknown"]) from exc
    np.random.seed(seed)
    torch.manual_seed(seed)


def _training_arguments(configuration: dict[str, Any], *, checkpoint_directory: Path) -> Any:
    try:
        from setfit import TrainingArguments
    except ModuleNotFoundError as exc:
        raise _missing_build_dependency_error([exc.name or "unknown"]) from exc
    parameters = dict(configuration["training_parameters"])
    parameters.pop("checkpoint_directory")
    return TrainingArguments(
        output_dir=str(checkpoint_directory),
        seed=configuration["random_seed"],
        **parameters,
    )


def _train_setfit(
    *,
    texts: list[str],
    labels: list[int],
    base_model: str,
    configuration: dict[str, Any],
    output_directory: Path,
    checkpoint_directory: Path,
) -> None:
    try:
        from datasets import Dataset
        from setfit import SetFitModel, Trainer
    except ModuleNotFoundError as exc:
        raise _missing_build_dependency_error([exc.name or "unknown"]) from exc
    model = SetFitModel.from_pretrained(
        base_model,
        labels=list(COMMUNITY_INTENT_CATALOG),
        device="cpu",
    )
    trainer = Trainer(
        model=model,
        args=_training_arguments(configuration, checkpoint_directory=checkpoint_directory),
        train_dataset=Dataset.from_dict({"text": texts, "label": labels}),
    )
    trainer.train()
    model.save_pretrained(output_directory)


def _require_clean_output(output_directory: Path) -> None:
    if output_directory.exists() and not output_directory.is_dir():
        raise ValueError("intent model output must be a directory")
    if output_directory.is_dir():
        unexpected = [path for path in output_directory.iterdir() if path.name != ".gitkeep"]
        if unexpected:
            raise ValueError("intent model output already contains an artifact; refusing to overwrite it")


def _validate_official_output(*, output_directory: Path, base_model: str) -> None:
    if output_directory.resolve() == DEFAULT_OUTPUT.resolve() and base_model != COMMUNITY_INTENT_BASE_MODEL:
        raise ValueError(
            "the official community-intent-v1 artifact must use intfloat/multilingual-e5-small"
        )


def build_model(args: argparse.Namespace) -> dict[str, Any]:
    _validate_build_dependencies()
    examples = load_training_dataset(args.dataset)
    dataset_manifest = load_and_validate_dataset_manifest(
        args.dataset_manifest,
        examples=examples,
    )
    source_configuration = load_training_configuration(args.config)
    configuration = effective_build_configuration(
        source_configuration,
        base_model_override=args.base_model,
    )
    output_directory = args.output.resolve()
    _validate_official_output(
        output_directory=output_directory,
        base_model=configuration["base_model"],
    )
    _require_clean_output(output_directory)
    _set_random_seeds(configuration["random_seed"])

    label_to_index = {label: index for index, label in enumerate(COMMUNITY_INTENT_CATALOG)}
    texts = [prepare_e5_classification_text(example.text) for example in examples]
    labels = [label_to_index[example.label] for example in examples]
    output_directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="community-intent-v1-build-",
        dir=output_directory.parent,
    ) as temporary:
        temporary_root = Path(temporary)
        temporary_artifact = temporary_root / "artifact"
        checkpoint_directory = temporary_root / configuration["training_parameters"]["checkpoint_directory"]
        temporary_artifact.mkdir()
        checkpoint_directory.mkdir()
        _train_setfit(
            texts=texts,
            labels=labels,
            base_model=configuration["base_model"],
            configuration=configuration,
            output_directory=temporary_artifact,
            checkpoint_directory=checkpoint_directory,
        )
        verify_setfit_artifact(temporary_artifact)
        output_directory.mkdir(parents=True, exist_ok=True)
        shutil.copytree(temporary_artifact, output_directory, dirs_exist_ok=True)

    verify_setfit_artifact(output_directory)
    artifact_digest = artifact_hash(output_directory)
    dataset_digest = dataset_hash(
        examples,
        dataset_version=COMMUNITY_INTENT_DATASET_VERSION,
    )
    configuration_digest = build_configuration_hash(configuration)
    manifest = build_artifact_manifest(
        artifact_digest=artifact_digest,
        dataset_digest=dataset_digest,
        build_configuration_digest=configuration_digest,
        base_model=configuration["base_model"],
    )
    manifest_path = write_artifact_manifest(output_directory, manifest)
    return {
        "status": "built",
        "output": str(output_directory),
        "manifest": str(manifest_path),
        "example_count": dataset_manifest["example_count"],
        "base_model": configuration["base_model"],
        "artifact_hash": artifact_digest,
        "dataset_hash": dataset_digest,
        "build_configuration_hash": configuration_digest,
    }


def main() -> int:
    result = build_model(build_parser().parse_args())
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
