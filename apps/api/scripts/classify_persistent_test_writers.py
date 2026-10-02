from __future__ import annotations

import json
from pathlib import Path

from inventory_persistent_test_writers import inspect_script

ROOT = Path(__file__).resolve().parent

DATABASE_ONLY = {
    "check_multimodal_retrieval_postgres_e2e.py",
    "check_processing_revision_selection_e2e.py",
    "check_visual_chunk_concurrency_e2e.py",
    "check_visual_chunk_revision_idempotency_e2e.py",
}


def dependency_profile(script_name: str) -> str:
    if script_name in DATABASE_ONLY:
        return "database_only"
    if script_name.startswith("smoke_") or script_name.startswith("check_worker_"):
        return "object_storage_and_worker"
    return "unclassified"


def main() -> int:
    records = []
    lifecycle_aware = []
    for path in sorted(ROOT.glob("*.py")):
        record = inspect_script(path)
        if not record or not record.get("writes_organization"):
            continue
        if record.get("uses_ephemeral_helper"):
            lifecycle_aware.append(record["script"])
            continue
        profile = dependency_profile(path.name)
        records.append({**record, "dependency_profile": profile})

    result = {
        "database_only": [item["script"] for item in records if item["dependency_profile"] == "database_only"],
        "object_storage_and_worker": [
            item["script"] for item in records if item["dependency_profile"] == "object_storage_and_worker"
        ],
        "lifecycle_aware": lifecycle_aware,
        "unclassified": [item["script"] for item in records if item["dependency_profile"] == "unclassified"],
    }
    result["classified_count"] = len(result["database_only"]) + len(result["object_storage_and_worker"])
    result["lifecycle_aware_count"] = len(result["lifecycle_aware"])
    result["unclassified_count"] = len(result["unclassified"])
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["unclassified_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
