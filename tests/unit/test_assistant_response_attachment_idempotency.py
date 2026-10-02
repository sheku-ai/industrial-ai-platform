from app.models.assistant_runtime import ConversationTurn

INDEX_NAME = "uq_ai_conversation_turns_assistant_response"
MIGRATION_PATH = (
    __import__("pathlib").Path(__file__).resolve().parents[2]
    / "apps/api/alembic/versions/20260816_998_assistant_response_attachment_idempotency.py"
)


def _load_migration():
    namespace = __import__("runpy").run_path(str(MIGRATION_PATH))
    return __import__("types").SimpleNamespace(**namespace)


class _MappingsResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> list[dict[str, object]]:
        return self._rows


class _Connection:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.statements: list[str] = []

    def execute(self, statement: object) -> _MappingsResult:
        self.statements.append(str(statement))
        return _MappingsResult(self.rows)


def test_conversation_turn_model_declares_assistant_response_attachment_identity() -> None:
    index = next(index for index in ConversationTurn.__table__.indexes if index.name == INDEX_NAME)

    assert index.unique is True
    assert [column.name for column in index.columns] == ["conversation_id", "assistant_response_id"]
    assert str(index.dialect_options["postgresql"]["where"]) == "assistant_response_id IS NOT NULL"


def test_migration_creates_unique_partial_index_after_clean_preflight(monkeypatch) -> None:
    migration = _load_migration()
    connection = _Connection([])
    created: list[tuple[tuple[object, ...], dict[str, object]]] = []

    monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
    monkeypatch.setattr(migration.op, "create_index", lambda *args, **kwargs: created.append((args, kwargs)))

    migration.upgrade()

    assert migration.revision == "20260816_998"
    assert migration.down_revision == "20260816_997"
    assert len(created) == 1
    args, kwargs = created[0]
    assert args == (INDEX_NAME, "conversation_turns", ["conversation_id", "assistant_response_id"])
    assert kwargs["unique"] is True
    assert kwargs["schema"] == "ai"
    assert str(kwargs["postgresql_where"]) == "assistant_response_id IS NOT NULL"
    assert "HAVING count(*) > 1" in connection.statements[0]


def test_migration_aborts_when_duplicate_attachments_exist(monkeypatch) -> None:
    migration = _load_migration()
    connection = _Connection(
        [
            {
                "conversation_id": "conversation-1",
                "assistant_response_id": "response-1",
                "turn_count": 2,
            }
        ]
    )
    created: list[tuple[tuple[object, ...], dict[str, object]]] = []

    monkeypatch.setattr(migration.op, "get_bind", lambda: connection)
    monkeypatch.setattr(migration.op, "create_index", lambda *args, **kwargs: created.append((args, kwargs)))

    try:
        migration.upgrade()
    except RuntimeError as exc:
        assert "duplicate attachments exist" in str(exc)
    else:
        raise AssertionError("migration must reject duplicate historical attachments")

    assert created == []
