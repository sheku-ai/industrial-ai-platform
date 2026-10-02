from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_admin_portal.py"


def test_fixed_endpoints_and_routes() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'API_URL = "http://127.0.0.1:8000"' in source
    assert 'PORTAL_URL = "http://127.0.0.1:3000"' in source
    for route in (
        "/operations",
        "/organization",
        "/documents",
        "/knowledge",
        "/connectors",
        "/runtime",
        "/scheduler",
        "/ai",
    ):
        assert f'"{route}"' in source


def test_rendering_and_api_contract_checks() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert '"html_present"' in source
    assert '"platform_title_present"' in source
    assert '"next_payload_present"' in source
    assert '"/platform/configuration"' in source
    assert 'configuration.get("portal_port") != 3000' in source
    assert '"/platform/status"' in source


def test_evidence_and_shutdown_contract() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "admin-portal-validation.json" in source
    assert 'evidence["status"] = "passed"' in source
    assert 'SUPERVISOR), "compose-down"' in source
    assert '"clean_shutdown"' in source
