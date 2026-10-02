from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from app.services.community_intent_model_artifact import (
    COMMUNITY_INTENT_BASE_MODEL,
    build_artifact_manifest,
    build_configuration_hash,
    effective_build_configuration,
    load_training_configuration,
    prepare_e5_classification_text,
)

RESOURCE_ROOT = Path("apps/api/resources/intent-models/community-intent-v1")


def _build_script() -> ModuleType:
    path = Path("scripts/build-community-intent-model.py")
    spec = importlib.util.spec_from_file_location("build_community_intent_model", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_training_configuration_declares_official_encoder_seed_and_parameters() -> None:
    configuration = load_training_configuration(RESOURCE_ROOT / "training-config.json")

    assert configuration["base_model"] == "intfloat/multilingual-e5-small"
    assert configuration["random_seed"] == 42
    assert configuration["training_parameters"]["batch_size"] == 16
    assert configuration["training_parameters"]["num_epochs"] == 4
    assert configuration["training_parameters"]["num_iterations"] == 20


def test_build_only_base_model_override_changes_configuration_identity() -> None:
    configuration = load_training_configuration(RESOURCE_ROOT / "training-config.json")
    official = effective_build_configuration(configuration)
    experimental = effective_build_configuration(
        configuration,
        base_model_override="example/experimental-encoder",
    )

    assert official["base_model"] == COMMUNITY_INTENT_BASE_MODEL
    assert experimental["base_model"] == "example/experimental-encoder"
    assert build_configuration_hash(official) != build_configuration_hash(experimental)


def test_build_configuration_and_manifest_identity_are_deterministic() -> None:
    configuration = load_training_configuration(RESOURCE_ROOT / "training-config.json")
    effective = effective_build_configuration(configuration)
    first_hash = build_configuration_hash(effective)
    second_hash = build_configuration_hash(dict(reversed(list(effective.items()))))
    manifest = build_artifact_manifest(
        artifact_digest="a" * 64,
        dataset_digest="d" * 64,
        build_configuration_digest=first_hash,
        base_model=effective["base_model"],
    )

    assert first_hash == second_hash
    assert "build_timestamp" not in manifest


def test_e5_input_preparation_is_shared_and_deterministic() -> None:
    assert prepare_e5_classification_text("  Explain   this  ") == "query: Explain this"
    assert prepare_e5_classification_text("query: Explain this") == "query: Explain this"


def test_cli_defaults_to_official_paths_and_encoder_contract() -> None:
    module = _build_script()
    args = module.build_parser().parse_args([])

    assert args.dataset == module.DEFAULT_DATASET
    assert args.config == module.DEFAULT_CONFIG
    assert args.output == module.DEFAULT_OUTPUT
    assert args.base_model is None


def test_official_output_rejects_encoder_override() -> None:
    module = _build_script()

    with pytest.raises(ValueError, match="official community-intent-v1"):
        module._validate_official_output(
            output_directory=module.DEFAULT_OUTPUT,
            base_model="example/experimental-encoder",
        )


def test_missing_build_dependency_has_explicit_error(monkeypatch) -> None:
    module = _build_script()

    monkeypatch.setattr(
        module.importlib.util,
        "find_spec",
        lambda name: None if name == "numpy" else object(),
    )

    with pytest.raises(RuntimeError, match="dependencies are missing: numpy") as exc_info:
        module._validate_build_dependencies()

    assert "apps/api/requirements-intent-build.txt" in str(exc_info.value)


def test_build_boundary_receives_declared_seed_without_training(monkeypatch, tmp_path: Path) -> None:
    module = _build_script()
    captured: dict[str, object] = {}

    monkeypatch.setattr(module, "_validate_build_dependencies", lambda: None)
    monkeypatch.setattr(module, "load_training_dataset", lambda path: ())
    monkeypatch.setattr(
        module,
        "load_and_validate_dataset_manifest",
        lambda path, examples: {"example_count": 0},
    )
    configuration = load_training_configuration(RESOURCE_ROOT / "training-config.json")
    monkeypatch.setattr(module, "load_training_configuration", lambda path: configuration)
    monkeypatch.setattr(module, "_set_random_seeds", lambda seed: captured.setdefault("seed", seed))
    monkeypatch.setattr(module, "_train_setfit", lambda **kwargs: captured.update(kwargs))
    monkeypatch.setattr(module, "verify_setfit_artifact", lambda path: None)
    monkeypatch.setattr(module, "artifact_hash", lambda path: "a" * 64)
    monkeypatch.setattr(module, "dataset_hash", lambda examples, dataset_version: "d" * 64)
    monkeypatch.setattr(module, "write_artifact_manifest", lambda path, manifest: path / "manifest.json")
    monkeypatch.setattr(module.shutil, "copytree", lambda source, destination, dirs_exist_ok: None)
    args = argparse.Namespace(
        dataset=tmp_path / "training.jsonl",
        dataset_manifest=tmp_path / "dataset-manifest.json",
        config=tmp_path / "training-config.json",
        output=tmp_path / "experimental-output",
        base_model="example/experimental-encoder",
    )

    module.build_model(args)

    assert captured["seed"] == 42
    assert captured["base_model"] == "example/experimental-encoder"
