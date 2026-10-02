from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_ROOT = ROOT / "apps" / "api" / "scripts"

KNOWN_SAFE_SCRIPTS = {
    "check_runtime_managed_services_e2e.py",
}


def _call_name(node: ast.Call) -> str:
    target = node.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        parts: list[str] = []
        current: ast.AST | None = target
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))
    return ""


def inspect_script(path: Path) -> dict[str, object] | None:
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return {
            "script": path.name,
            "parse_error": str(exc),
            "writes_organization": False,
            "uses_ephemeral_helper": False,
            "signals": [],
        }

    signals: set[str] = set()
    writes_organization = False
    uses_ephemeral_helper = "create_ephemeral_organization" in source

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name.endswith("Organization"):
                writes_organization = True
                signals.add("organization_constructor")
            if name.endswith("session.add") or name == "session.add":
                signals.add("session_add")
            if name.endswith("session.execute") or name == "session.execute":
                signals.add("session_execute")
        elif isinstance(node, ast.ImportFrom):
            if node.module == "app.models.core" and any(alias.name == "Organization" for alias in node.names):
                signals.add("organization_import")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value.lower()
            if "insert into core.organizations" in value:
                writes_organization = True
                signals.add("raw_organization_insert")

    is_e2e = path.name.endswith("_e2e.py")
    if not is_e2e and not writes_organization:
        return None

    return {
        "script": path.name,
        "is_e2e": is_e2e,
        "writes_organization": writes_organization,
        "uses_ephemeral_helper": uses_ephemeral_helper,
        "known_safe": path.name in KNOWN_SAFE_SCRIPTS,
        "signals": sorted(signals),
    }


def main() -> int:
    records = [record for path in sorted(SCRIPTS_ROOT.glob("*.py")) if (record := inspect_script(path)) is not None]

    writers = [record for record in records if record["writes_organization"]]
    unclassified = [record for record in writers if not record["uses_ephemeral_helper"] and not record["known_safe"]]

    result = {
        "scripts_scanned": len(list(SCRIPTS_ROOT.glob("*.py"))),
        "e2e_scripts": sum(1 for record in records if record.get("is_e2e")),
        "organization_writers": len(writers),
        "ephemeral_helper_writers": sum(1 for record in writers if record["uses_ephemeral_helper"]),
        "unclassified_writer_count": len(unclassified),
        "unclassified_writers": [record["script"] for record in unclassified],
        "writers": writers,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
