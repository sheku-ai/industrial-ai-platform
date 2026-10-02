import importlib.util
from pathlib import Path

from app.models.ingestion import IngestionPipelineProfile as Profile

p = Path(__file__).with_name("check_worker_text_source_e2e.py")
s = importlib.util.spec_from_file_location("target", p)
m = importlib.util.module_from_spec(s)
s.loader.exec_module(m)


def factory(*a, **k):
    k["adapter_policies"] = [
        {"adapter_key": "platform.text.plain", "enabled": True, "priority": 100, "allowed_media_types": ["text/plain"]}
    ]
    k["adapter_versions"] = {"platform.text.plain": "1.0.0"}
    return Profile(*a, **k)


m.IngestionPipelineProfile = factory
raise SystemExit(m.main())
