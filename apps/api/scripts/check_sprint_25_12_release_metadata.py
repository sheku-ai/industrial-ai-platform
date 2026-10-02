import json
from pathlib import Path

REQUIRED = (
    "check_sprint_25_12_platform_regression.py",
    "check_portal_platform_contract.py",
    "check_runtime_production_alignment_contract.py",
    "check_runtime_capacity_backpressure_contract.py",
)


def main():
    root = Path(__file__).resolve().parent
    checks = {name: (root / name).is_file() for name in REQUIRED}
    passed = all(checks.values())
    print(json.dumps({"passed": passed, "required_checks": checks}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
