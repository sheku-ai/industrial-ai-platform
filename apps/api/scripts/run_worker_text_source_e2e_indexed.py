import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from app.db.session import SessionLocal
from app.models.documents import DocumentVersion
from app.models.runtime import RuntimeExecution


def load_target():
    path = Path(__file__).with_name("run_worker_text_source_e2e_fixed.py")
    spec = importlib.util.spec_from_file_location("worker_text_source_e2e_fixed", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load worker text source e2e")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    output = io.StringIO()
    with redirect_stdout(output):
        load_target().m.main()
    payload = json.loads(output.getvalue().strip())

    session = SessionLocal()
    try:
        execution = session.get(RuntimeExecution, payload["execution_id"])
        version = session.get(DocumentVersion, execution.subject_id)
        indexed = version.status == "indexed"
        snapshot_indexed = (version.source_snapshot or {}).get("last_ingestion_status") == "indexed"
    finally:
        session.close()

    payload["document_version_succeeded"] = indexed
    payload["document_version_indexed"] = indexed
    payload["status_snapshot_indexed"] = snapshot_indexed
    payload["passed"] = all(
        value is True
        for key, value in payload.items()
        if key not in {"passed", "artifact_id", "attempt_id", "execution_id", "chunk_count", "record_count"}
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
