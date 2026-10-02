from app.services.migration_safety import evaluate_migration_safety


def test_single_matching_head_is_compatible() -> None:
    report = evaluate_migration_safety(
        repository_heads=["head_a"],
        database_heads=["head_a"],
        known_revisions=["base", "head_a"],
    )

    assert report.compatibility == "compatible"
    assert report.startup_compatible is True
    assert report.migration_required is False


def test_pending_forward_migrations_are_identified() -> None:
    report = evaluate_migration_safety(
        repository_heads=["head_b"],
        database_heads=["head_a"],
        known_revisions=["base", "head_a", "head_b"],
        pending_revisions=["head_b"],
    )

    assert report.compatibility == "pending"
    assert report.startup_compatible is False
    assert report.migration_required is True
    assert report.pending_revisions == ("head_b",)


def test_multiple_repository_heads_block_startup() -> None:
    report = evaluate_migration_safety(
        repository_heads=["head_a", "head_b"],
        database_heads=["head_a"],
        known_revisions=["head_a", "head_b"],
    )

    assert report.compatibility == "multiple_repository_heads"
    assert report.startup_compatible is False


def test_multiple_database_heads_block_startup() -> None:
    report = evaluate_migration_safety(
        repository_heads=["head_b"],
        database_heads=["head_a", "head_b"],
        known_revisions=["head_a", "head_b"],
    )

    assert report.compatibility == "multiple_database_heads"
    assert report.startup_compatible is False


def test_unknown_database_revision_blocks_startup() -> None:
    report = evaluate_migration_safety(
        repository_heads=["head_b"],
        database_heads=["external_head"],
        known_revisions=["head_a", "head_b"],
    )

    assert report.compatibility == "unknown_database_revision"
    assert report.startup_compatible is False


def test_unversioned_database_requires_migration() -> None:
    report = evaluate_migration_safety(
        repository_heads=["head_a"],
        database_heads=[],
        known_revisions=["head_a"],
        pending_revisions=["head_a"],
    )

    assert report.compatibility == "unversioned"
    assert report.migration_required is True
