from app.core.config import Settings


def test_cors_origin_parser_trims_and_discards_empty_values() -> None:
    settings = Settings(cors_allowed_origins=" http://localhost:3000, ,http://127.0.0.1:3100 ")

    assert settings.cors_origins == [
        "http://localhost:3000",
        "http://127.0.0.1:3100",
    ]


def test_cors_origins_are_derived_from_portal_port() -> None:
    settings = Settings(portal_port=3100, cors_allowed_origins="")

    assert settings.cors_origins == [
        "http://localhost:3100",
        "http://127.0.0.1:3100",
    ]


def test_explicit_cors_origins_override_portal_port_defaults() -> None:
    settings = Settings(
        portal_port=3100,
        cors_allowed_origins="https://portal.example.test",
    )

    assert settings.cors_origins == ["https://portal.example.test"]
