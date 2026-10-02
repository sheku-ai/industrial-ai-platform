from __future__ import annotations

from pathlib import Path

import pytest

from app.services.community_intent_model_artifact import (
    COMMUNITY_INTENT_ARTIFACT_REFERENCE,
    COMMUNITY_INTENT_BASE_MODEL,
    artifact_hash,
    build_artifact_manifest,
    load_and_validate_artifact_manifest,
    verify_setfit_artifact,
    write_artifact_manifest,
)


def _artifact(root: Path, *, reverse: bool = False) -> Path:
    files = [
        ("config.json", b'{"architectures":["ExampleModel"]}'),
        ("config_setfit.json", b'{"labels":["knowledge_query"]}'),
        ("model_head.pkl", b"classification-head"),
        ("modules.json", b"[]"),
        ("model.safetensors", b"weights"),
        ("tokenizer.json", b'{"version":"1.0"}'),
        ("tokenizer_config.json", b'{"model_max_length":512}'),
        ("1_Pooling/config.json", b'{"pooling_mode_mean_tokens":true}'),
    ]
    for relative, content in reversed(files) if reverse else files:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return root


def test_artifact_hash_is_host_and_file_order_independent(tmp_path: Path) -> None:
    first = _artifact(tmp_path / "host-a")
    second = _artifact(tmp_path / "different" / "absolute" / "host-b", reverse=True)

    assert artifact_hash(first) == artifact_hash(second)


def test_artifact_hash_excludes_manifest_and_temporary_files(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path / "artifact")
    baseline = artifact_hash(artifact)
    (artifact / "temporary.tmp").write_text("volatile", encoding="utf-8")
    (artifact / ".DS_Store").write_text("volatile", encoding="utf-8")
    manifest = build_artifact_manifest(
        artifact_digest=baseline,
        dataset_digest="d" * 64,
        build_configuration_digest="c" * 64,
        base_model=COMMUNITY_INTENT_BASE_MODEL,
    )
    write_artifact_manifest(artifact, {**manifest, "build_timestamp": "volatile"})

    assert artifact_hash(artifact) == baseline


def test_artifact_manifest_has_offline_runtime_contract(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path / "artifact")
    manifest = build_artifact_manifest(
        artifact_digest=artifact_hash(artifact),
        dataset_digest="d" * 64,
        build_configuration_digest="c" * 64,
        base_model=COMMUNITY_INTENT_BASE_MODEL,
    )
    path = write_artifact_manifest(artifact, manifest)

    loaded = load_and_validate_artifact_manifest(path)

    assert loaded["artifact_reference"] == COMMUNITY_INTENT_ARTIFACT_REFERENCE
    assert loaded["offline_runtime"] is True
    assert loaded["base_model"] == "intfloat/multilingual-e5-small"


def test_artifact_contract_rejects_duplicate_weight_formats(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path / "artifact")
    (artifact / "pytorch_model.bin").write_bytes(b"duplicate weights")

    with pytest.raises(ValueError, match="duplicate model weight"):
        verify_setfit_artifact(artifact)


def test_artifact_contract_requires_local_tokenizer_data(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path / "artifact")
    (artifact / "tokenizer.json").unlink()

    with pytest.raises(ValueError, match="tokenizer data"):
        verify_setfit_artifact(artifact)


def test_artifact_manifest_rejects_non_hex_digest(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path / "artifact")
    manifest = build_artifact_manifest(
        artifact_digest="not-a-sha256-digest".ljust(64, "x"),
        dataset_digest="d" * 64,
        build_configuration_digest="c" * 64,
        base_model=COMMUNITY_INTENT_BASE_MODEL,
    )
    path = write_artifact_manifest(artifact, manifest)

    with pytest.raises(ValueError, match="artifact_hash"):
        load_and_validate_artifact_manifest(path)
