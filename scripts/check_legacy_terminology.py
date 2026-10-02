from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = (
    ROOT / "apps" / "api" / "app",
    ROOT / "apps" / "admin-portal",
    ROOT / "scripts",
)
TEXT_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".yaml", ".yml", ".sql"}
EXCLUDED_PARTS = {".git", ".next", ".venv", "node_modules", "runtime", "__pycache__"}
PROHIBITED_TERMS = {
    "legacy_product_prefix": ("ia-om", "ia_om", "iaom"),
    "legacy_vector_collection": ("docs_v2",),
    "fixed_plant_entity": ("plant_id", "plant_name", "plant_code", "plant_type"),
    "fixed_site_entity": ("site_id", "site_name", "site_code", "site_type"),
    "fixed_asset_entity": ("wind_farm", "solar_farm"),
}


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    line: int
    excerpt: str


def candidate_files() -> list[Path]:
    files: list[Path] = []
    for root in SCAN_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            if path.name == Path(__file__).name:
                continue
            if any(part in EXCLUDED_PARTS for part in path.parts):
                continue
            files.append(path)
    return sorted(files)


def scan() -> list[Finding]:
    findings: list[Finding] = []
    for path in candidate_files():
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line_number, line in enumerate(lines, start=1):
            normalized = line.lower()
            for rule, terms in PROHIBITED_TERMS.items():
                if any(term in normalized for term in terms):
                    findings.append(
                        Finding(
                            rule=rule,
                            path=path.relative_to(ROOT).as_posix(),
                            line=line_number,
                            excerpt=line.strip()[:240],
                        )
                    )
    return findings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Detect prohibited legacy terminology in executable product code")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    files = candidate_files()
    findings = scan()
    payload = {
        "status": "passed" if not findings else "failed",
        "scanned_files": len(files),
        "finding_count": len(findings),
        "findings": [asdict(item) for item in findings],
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Legacy terminology scan: {payload['status']}")
        print(f"Scanned files: {payload['scanned_files']}")
        print(f"Findings: {payload['finding_count']}")
        for item in findings:
            print(f"- {item.rule}: {item.path}:{item.line}: {item.excerpt}")
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
