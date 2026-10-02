from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_report_atomic(path: str, report: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=str(target.parent), encoding="utf-8") as tmp:
        json.dump(report, tmp, indent=2, sort_keys=True, default=str)
        tmp.write("\n")
        tmp_path = tmp.name
    os.replace(tmp_path, target)
