from app.models.processing import ProcessingRevision


def test_processing_revision_table_contract():
    table = ProcessingRevision.__table__
    assert table.schema == "documents"
    assert table.name == "processing_revisions"
    assert table.c.runtime_execution_id.nullable is False
    assert table.c.runtime_attempt_id.nullable is False


def test_processing_revision_runtime_attempt_is_unique():
    names = {constraint.name for constraint in ProcessingRevision.__table__.constraints}
    assert "uq_processing_revisions_runtime_attempt" in names
