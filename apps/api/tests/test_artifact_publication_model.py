from app.models.artifact_publication import RuntimeArtifactPublication


def test_artifact_publication_model_contract():
    table = RuntimeArtifactPublication.__table__

    assert table.schema == "runtime"
    assert table.name == "artifact_publications"
    assert table.c.publication_number.nullable is False
    assert table.c.storage_uri.nullable is False
    assert table.c.metadata.name == "metadata"

    constraint_names = {constraint.name for constraint in table.constraints}
    assert "fk_runtime_artifact_publications_artifact" in constraint_names
    assert "fk_runtime_artifact_publications_attempt" in constraint_names
    assert "uq_runtime_artifact_publications_number" in constraint_names
    assert "ck_runtime_artifact_publications_status" in constraint_names
    assert "ck_runtime_artifact_publications_verified_after_publish" in constraint_names

    index_names = {index.name for index in table.indexes}
    assert "ix_runtime_artifact_publications_status" in index_names
    assert "ix_runtime_artifact_publications_artifact" in index_names
