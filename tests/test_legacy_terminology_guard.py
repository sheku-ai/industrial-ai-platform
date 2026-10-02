from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCANNER = ROOT / "scripts" / "check_legacy_terminology.py"


def test_legacy_terminology_scanner_exists_and_targets_product_code() -> None:
    source = SCANNER.read_text(encoding="utf-8")

    assert 'ROOT / "apps" / "api" / "app"' in source
    assert 'ROOT / "apps" / "admin-portal"' in source
    assert 'ROOT / "scripts"' in source
    assert '"docs_v2"' in source
    assert '"plant_id"' in source
    assert '"site_id"' in source
    assert '"wind_farm"' in source
    assert '"solar_farm"' in source


def test_legacy_terminology_scanner_excludes_generated_and_runtime_content() -> None:
    source = SCANNER.read_text(encoding="utf-8")

    assert '".next"' in source
    assert '"node_modules"' in source
    assert '"runtime"' in source
    assert '".venv"' in source


def test_legacy_terminology_scanner_fails_when_findings_exist() -> None:
    source = SCANNER.read_text(encoding="utf-8")

    assert '"status": "passed" if not findings else "failed"' in source
    assert "return 0 if not findings else 1" in source
    assert '"--json"' in source
