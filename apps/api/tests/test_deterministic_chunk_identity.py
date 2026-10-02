from app.services.deterministic_chunk_identity import build_deterministic_chunk_identity


def test_equivalent_inputs_produce_same_identity():
    first = build_deterministic_chunk_identity(
        normalized_text="Section text\nSecond line  ",
        structural_path=["chapter-1", "section-2"],
        metadata={"page": 3, "language": "en"},
    )
    second = build_deterministic_chunk_identity(
        normalized_text="Section text\nSecond line",
        structural_path=["chapter-1", "section-2"],
        metadata={"language": "en", "page": 3},
    )

    assert first == second
    assert first.chunk_key.startswith("chapter-1/section-2:")
    assert len(first.content_hash) == 64


def test_structural_path_changes_chunk_key_without_changing_content_hash():
    first = build_deterministic_chunk_identity(
        normalized_text="same content",
        structural_path=["section-a"],
    )
    second = build_deterministic_chunk_identity(
        normalized_text="same content",
        structural_path=["section-b"],
    )

    assert first.content_hash == second.content_hash
    assert first.chunk_key != second.chunk_key


def test_content_change_changes_content_hash_and_chunk_key():
    first = build_deterministic_chunk_identity(normalized_text="version one")
    second = build_deterministic_chunk_identity(normalized_text="version two")

    assert first.content_hash != second.content_hash
    assert first.chunk_key != second.chunk_key


def test_composed_and_decomposed_unicode_produce_same_identity():
    composed = build_deterministic_chunk_identity(
        normalized_text="Café técnico",
        structural_path=["Sección"],
        metadata={"label": "Revisión"},
    )
    decomposed = build_deterministic_chunk_identity(
        normalized_text="Cafe\u0301 te\u0301cnico",
        structural_path=["Seccio\u0301n"],
        metadata={"label": "Revisio\u0301n"},
    )

    assert composed == decomposed


def test_crlf_and_lf_produce_same_identity():
    windows = build_deterministic_chunk_identity(
        normalized_text="first line\r\nsecond line\r\n",
    )
    unix = build_deterministic_chunk_identity(
        normalized_text="first line\nsecond line\n",
    )

    assert windows == unix
