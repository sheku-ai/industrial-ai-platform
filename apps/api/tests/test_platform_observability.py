from types import SimpleNamespace

from app.services.configuration_revision import resolve_configuration_revision
from app.services.database_revision import resolve_database_revision


class _Scalars:
    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


class _Result:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return _Scalars(self._values)


class _Session:
    def __init__(self, values=None, fail=False):
        self.values = values or []
        self.fail = fail
        self.rolled_back = False

    def execute(self, _statement):
        if self.fail:
            raise RuntimeError("database unavailable")
        return _Result(self.values)

    def rollback(self):
        self.rolled_back = True


def test_configuration_revision_is_deterministic_and_ignores_secrets() -> None:
    base = dict(
        app_name="Industrial AI Platform API",
        app_version="1.3.1",
        object_storage_access_key="first",
        object_storage_secret_key="secret-a",
    )
    first = resolve_configuration_revision(SimpleNamespace(**base))
    second = resolve_configuration_revision(
        SimpleNamespace(**{**base, "object_storage_access_key": "second", "object_storage_secret_key": "secret-b"})
    )

    assert first == second
    assert first.startswith("sha256:")
    assert len(first) == 23


def test_configuration_revision_changes_for_effective_setting() -> None:
    first = resolve_configuration_revision(SimpleNamespace(feature_worker_enabled=False))
    second = resolve_configuration_revision(SimpleNamespace(feature_worker_enabled=True))
    assert first != second


def test_database_revision_returns_alembic_heads() -> None:
    assert resolve_database_revision(_Session(["20260621_0040"])) == "20260621_0040"


def test_database_revision_handles_unavailable_database() -> None:
    session = _Session(fail=True)
    assert resolve_database_revision(session) == "unavailable"
    assert session.rolled_back is True


def test_database_revision_without_session_is_unavailable() -> None:
    assert resolve_database_revision(None) == "unavailable"
