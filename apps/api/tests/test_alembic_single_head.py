from pathlib import Path


def test_merge_revision_unifies_sprint_21_heads():
    migration = Path("alembic/versions/20260619_2150_merge_heads.py").read_text(encoding="utf-8")

    assert 'revision: str = "20260619_2150"' in migration
    assert '("20260619_2130", "20260619_2140")' in migration
