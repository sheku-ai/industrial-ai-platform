import importlib.util
import json
import sys
from argparse import Namespace
from contextlib import suppress
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "smoke_ingestion_platform.py"
SPEC = importlib.util.spec_from_file_location("smoke_ingestion_platform", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def make_args(tmp_path):
    return Namespace(
        api_url="http://127.0.0.1:8000",
        database_url="postgresql://example",
        evidence_dir=str(tmp_path),
        timeout_seconds=1,
        execution_id=None,
        expected_status="succeeded",
        stages="infrastructure",
    )


def test_stage_evidence_is_written_on_success(tmp_path):
    runner = MODULE.SmokeRunner(make_args(tmp_path))

    runner.run_stage(1, "example", lambda: [{"check": "ok"}])
    runner.write_summary()

    stage = json.loads((tmp_path / "01-example.json").read_text(encoding="utf-8"))
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert stage["status"] == "passed"
    assert summary["passed"] is True


def test_stage_evidence_is_written_on_failure(tmp_path):
    runner = MODULE.SmokeRunner(make_args(tmp_path))

    def fail():
        raise MODULE.SmokeFailure("controlled failure")

    with suppress(MODULE.SmokeFailure):
        runner.run_stage(1, "example", fail)

    stage = json.loads((tmp_path / "01-example.json").read_text(encoding="utf-8"))
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert stage["status"] == "failed"
    assert stage["error"] == "controlled failure"
    assert summary["passed"] is False


def test_require_raises_smoke_failure():
    try:
        MODULE.require(False, "failed check")
    except MODULE.SmokeFailure as exc:
        assert str(exc) == "failed check"
    else:
        raise AssertionError("SmokeFailure was not raised")
