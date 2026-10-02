#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from quality_gate_results import (
    REQUIRED_STAGE_BLOCKING,
    aggregate_results,
)

SEVERITIES = ("info", "low", "moderate", "high", "critical")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render the consolidated containerized Quality Gate report.")
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--worktree-dirty", choices=("true", "false"), required=True)
    parser.add_argument("--started-at", required=True)
    parser.add_argument("--completed-at", required=True)
    parser.add_argument("--duration-seconds", type=float, required=True)
    parser.add_argument("--compose-project", required=True)
    parser.add_argument("--release", action="store_true")
    return parser.parse_args()


def load_results(path: Path) -> dict[str, dict[str, Any]]:
    stages: dict[str, dict[str, Any]] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        fields = raw_line.split("\t")
        if len(fields) != 6:
            raise ValueError(f"invalid result record at line {line_number}")
        name, blocking, exit_code, duration, summary, log_path = fields
        if name in stages:
            raise ValueError(f"duplicate stage result at line {line_number}: {name}")
        code = int(exit_code)
        stages[name] = {
            "status": "passed" if code == 0 else "failed",
            "blocking": blocking == "true",
            "exit_code": code,
            "duration_seconds": round(float(duration), 3),
            "summary": summary,
            "log": log_path,
        }
    missing = sorted(set(REQUIRED_STAGE_BLOCKING) - set(stages))
    if missing:
        raise ValueError(f"missing required stages: {', '.join(missing)}")
    unexpected = sorted(set(stages) - set(REQUIRED_STAGE_BLOCKING))
    if unexpected:
        raise ValueError(f"unexpected stages: {', '.join(unexpected)}")
    for name, expected_blocking in REQUIRED_STAGE_BLOCKING.items():
        if stages[name]["blocking"] is not expected_blocking:
            raise ValueError(
                f"stage {name} blocking flag mismatch: expected {expected_blocking}, "
                f"got {stages[name]['blocking']}"
            )
    return stages


def parse_pytest(stage: dict[str, Any], report_root: Path) -> None:
    log_path = report_root / stage["log"]
    if not log_path.is_file():
        return
    text = log_path.read_text(encoding="utf-8", errors="replace")
    counts: dict[str, int] = {}
    collected = re.findall(r"\bcollected\s+(\d+)\s+items?\b", text)
    if collected:
        counts["collected"] = int(collected[-1])
    for label in ("passed", "failed", "skipped", "warnings", "warning", "errors", "error"):
        matches = re.findall(rf"(?<!\d)(\d+)\s+{label}\b", text)
        if matches:
            normalized = {"warning": "warnings", "error": "errors"}.get(label, label)
            counts[normalized] = int(matches[-1])
    if counts:
        stage["details"] = {"pytest": counts}


def load_json_log(stage: dict[str, Any], report_root: Path) -> dict[str, Any] | None:
    path = report_root / stage["log"]
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    decoder = json.JSONDecoder()
    candidates: list[dict[str, Any]] = []
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            candidates.append(payload)
    for payload in reversed(candidates):
        if "metadata" in payload and "vulnerabilities" in payload:
            return payload
    return candidates[-1] if candidates else None


def version_tuple(version: str) -> tuple[int, int, int] | None:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)
    return tuple(int(part) for part in match.groups()) if match else None


def minimum_fixed_from_range(affected_range: str) -> str | None:
    upper_bounds = re.findall(r"(<|<=)\s*(\d+\.\d+\.\d+)", affected_range)
    if not upper_bounds:
        hyphen = re.search(r"\d+\.\d+\.\d+\s+-\s+(\d+\.\d+\.\d+)", affected_range)
        if not hyphen:
            return None
        upper_bounds = [("<=", hyphen.group(1))]
    candidates: list[tuple[int, int, int]] = []
    for operator, version in upper_bounds:
        parsed = version_tuple(version)
        if parsed is None:
            continue
        major, minor, patch = parsed
        candidates.append(parsed if operator == "<" else (major, minor, patch + 1))
    if not candidates:
        return None
    selected = max(candidates)
    return ".".join(str(part) for part in selected)


def lockfile_versions(report_root: Path) -> dict[str, list[str]]:
    lock_path = report_root / "package-lock.json"
    if not lock_path.is_file():
        return {}
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    packages = payload.get("packages", {})
    versions: dict[str, set[str]] = {}
    if not isinstance(packages, dict):
        return {}
    for path, metadata in packages.items():
        if "node_modules/" not in path or not isinstance(metadata, dict):
            continue
        name = path.rsplit("node_modules/", 1)[-1]
        version = metadata.get("version")
        if name and isinstance(version, str):
            versions.setdefault(name, set()).add(version)
    return {name: sorted(items) for name, items in versions.items()}


def audit_details(payload: dict[str, Any], installed: dict[str, list[str]]) -> dict[str, Any]:
    metadata = payload.get("metadata", {})
    counts = metadata.get("vulnerabilities", {}) if isinstance(metadata, dict) else {}
    by_severity = {severity: int(counts.get(severity, 0) or 0) for severity in SEVERITIES}
    vulnerabilities = payload.get("vulnerabilities", {})
    if not isinstance(vulnerabilities, dict):
        vulnerabilities = {}

    direct = 0
    transitive = 0
    reported_fixes: list[dict[str, Any]] = []
    semver_major_fixes: list[dict[str, Any]] = []
    packages: list[dict[str, Any]] = []
    for name, item in sorted(vulnerabilities.items()):
        if not isinstance(item, dict):
            continue
        is_direct = bool(item.get("isDirect"))
        direct += int(is_direct)
        transitive += int(not is_direct)
        package = {
            "name": str(name),
            "severity": str(item.get("severity", "unknown")),
            "direct": is_direct,
            "range": str(item.get("range", "unknown")),
            "installed_versions": installed.get(str(name), []),
        }
        advisories = []
        for advisory in item.get("via", []):
            if not isinstance(advisory, dict):
                continue
            affected_range = str(advisory.get("range", "unknown"))
            url = str(advisory.get("url", ""))
            advisories.append(
                {
                    "id": url.rstrip("/").rsplit("/", 1)[-1] if url else str(advisory.get("source", "unknown")),
                    "title": str(advisory.get("title", "unknown")),
                    "severity": str(advisory.get("severity", "unknown")),
                    "affected_range": affected_range,
                    "inferred_first_unaffected_version": minimum_fixed_from_range(affected_range),
                    "url": url,
                }
            )
        package["advisories"] = advisories
        fixed_versions = [
            advisory["inferred_first_unaffected_version"]
            for advisory in advisories
            if advisory["inferred_first_unaffected_version"] is not None
        ]
        package["inferred_first_unaffected_versions"] = sorted(
            set(fixed_versions), key=lambda value: version_tuple(value) or (0, 0, 0)
        )
        package["compatibility_status"] = "not_validated"
        fix = item.get("fixAvailable")
        if isinstance(fix, dict):
            is_semver_major = bool(fix.get("isSemVerMajor"))
            update = {
                "name": str(fix.get("name", name)),
                "version": str(fix.get("version", "unknown")),
                "is_semver_major": is_semver_major,
            }
            if is_semver_major:
                semver_major_fixes.append(update)
            else:
                reported_fixes.append(update)
            package["npm_fix_available"] = update
            package["fix_without_semver_major"] = not is_semver_major
            package["compatibility_status"] = "npm_semver_assessment_only"
        elif fix is True:
            package["npm_fix_available"] = True
            package["fix_without_semver_major"] = None
            reported_fixes.append(
                {
                    "name": str(name),
                    "version": "target not reported",
                    "is_semver_major": None,
                }
            )
        else:
            package["npm_fix_available"] = False
            package["fix_without_semver_major"] = None
        packages.append(package)

    return {
        "by_severity": by_severity,
        "direct_vulnerable_dependencies": direct,
        "transitive_vulnerable_dependencies": transitive,
        "npm_reported_fixes": reported_fixes,
        "npm_reported_semver_major_fixes": semver_major_fixes,
        "vulnerable_packages": packages,
    }


def development_audit_delta(
    production: dict[str, Any], complete: dict[str, Any]
) -> dict[str, Any]:
    production_names = {item["name"] for item in production["vulnerable_packages"]}
    complete_names = {item["name"] for item in complete["vulnerable_packages"]}
    severity_delta = {
        severity: complete["by_severity"][severity] - production["by_severity"][severity]
        for severity in SEVERITIES
    }
    return {
        "development_only_vulnerable_packages": sorted(complete_names - production_names),
        "development_only_by_severity": severity_delta,
        "development_delta_consistent": all(value >= 0 for value in severity_delta.values())
        and production_names.issubset(complete_names),
    }


def pip_audit_details(payload: list[dict[str, Any]]) -> dict[str, Any]:
    vulnerable = []
    advisory_records: list[dict[str, Any]] = []
    for dependency in payload:
        vulnerabilities = dependency.get("vulns", [])
        if not isinstance(vulnerabilities, list) or not vulnerabilities:
            continue
        normalized_vulnerabilities = []
        for item in vulnerabilities:
            if not isinstance(item, dict):
                continue
            normalized = {
                "id": str(item.get("id", "unknown")),
                "aliases": sorted(str(alias) for alias in item.get("aliases", [])),
                "advisory_fixed_versions": sorted(
                    str(version) for version in item.get("fix_versions", [])
                ),
            }
            normalized_vulnerabilities.append(normalized)
            advisory_records.append(normalized)
        vulnerable.append(
            {
                "name": str(dependency.get("name", "unknown")),
                "version": str(dependency.get("version", "unknown")),
                "production_runtime": True,
                "vulnerability_ids": [item["id"] for item in normalized_vulnerabilities],
                "advisory_fixed_versions": sorted(
                    {
                        str(version)
                        for item in normalized_vulnerabilities
                        for version in item["advisory_fixed_versions"]
                    }
                ),
                "validated_compatible_versions": [],
                "compatibility_status": "not_validated_by_pip_audit",
                "advisories": normalized_vulnerabilities,
            }
        )

    parent = list(range(len(advisory_records)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    identifiers: dict[str, int] = {}
    for index, advisory in enumerate(advisory_records):
        for identifier in [advisory["id"], *advisory["aliases"]]:
            existing = identifiers.get(identifier)
            if existing is None:
                identifiers[identifier] = index
            else:
                union(index, existing)
    groups: dict[int, set[str]] = {}
    for index, advisory in enumerate(advisory_records):
        groups.setdefault(find(index), set()).update([advisory["id"], *advisory["aliases"]])
    duplicate_groups = [sorted(group) for group in groups.values() if len(group) > 1]

    return {
        "audited_dependencies": len(payload),
        "vulnerable_dependencies": len(vulnerable),
        "raw_advisory_records": len(advisory_records),
        "unique_primary_advisory_ids": len({item["id"] for item in advisory_records}),
        "deduplicated_vulnerability_groups": len(groups),
        "duplicate_advisory_records": len(advisory_records) - len(groups),
        "alias_identifier_count": len(
            {alias for advisory in advisory_records for alias in advisory["aliases"]}
        ),
        "duplicate_or_alias_groups": duplicate_groups,
        "all_affected_packages_are_production_runtime": True,
        "version_interpretation": "advisory_fixes_only_not_compatibility_validated",
        "packages": vulnerable,
    }


def enrich_audits(stages: dict[str, dict[str, Any]], report_root: Path) -> None:
    details_by_name: dict[str, dict[str, Any]] = {}
    installed = lockfile_versions(report_root)
    for name in ("npm_audit_production", "npm_audit_all"):
        payload = load_json_log(stages[name], report_root)
        if payload is not None:
            details = audit_details(payload, installed)
            stages[name]["details"] = details
            details_by_name[name] = details

    production = details_by_name.get("npm_audit_production")
    complete = details_by_name.get("npm_audit_all")
    if production and complete:
        complete.update(development_audit_delta(production, complete))

    python_stage = stages["python_audit"]
    python_path = report_root / python_stage["log"]
    if not python_path.is_file():
        return
    text = python_path.read_text(encoding="utf-8", errors="replace")
    decoder = json.JSONDecoder()
    candidates: list[list[Any]] = []
    for index, character in enumerate(text):
        if character != "[":
            continue
        try:
            candidate, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if (
            isinstance(candidate, list)
            and candidate
            and all(isinstance(item, dict) for item in candidate)
            and all({"name", "version", "vulns"}.issubset(item) for item in candidate)
        ):
            candidates.append(candidate)
    if not candidates:
        return
    payload = max(candidates, key=len)
    python_stage["details"] = pip_audit_details(payload)


def markdown(report: dict[str, Any]) -> str:
    blocking_failures = [
        name
        for name, stage in report["stages"].items()
        if stage["blocking"] and stage["status"] != "passed"
    ]
    lines = [
        "# Industrial AI Platform Quality Gate",
        "",
        f"- Overall status: **{report['overall_status'].upper()}**",
        f"- Exit code: `{report['overall_exit_code']}`",
        f"- Commit: `{report['commit_sha']}`",
        f"- Branch: `{report['branch']}`",
        f"- Worktree dirty: `{str(report['worktree_dirty']).lower()}`",
        f"- Compose project: `{report['compose_project']}`",
        f"- Mode: `{'release' if report['release'] else 'native'}`",
        f"- Started: `{report['started_at']}`",
        f"- Completed: `{report['completed_at']}`",
        f"- Duration: `{report['duration_seconds']:.3f}s`",
        "",
        "## Blocking result",
        "",
    ]
    if blocking_failures:
        lines.append("Blocked by: " + ", ".join(f"`{name}`" for name in blocking_failures) + ".")
    else:
        lines.append("All blocking gates passed.")
    lines.extend(
        [
            "",
            "## Stages",
            "",
            "| Stage | Status | Blocking | Exit | Duration | Summary |",
            "|---|---|---:|---:|---:|---|",
        ]
    )
    for name, stage in report["stages"].items():
        summary = str(stage["summary"]).replace("|", "\\|")
        lines.append(
            f"| `{name}` | {stage['status']} | {'yes' if stage['blocking'] else 'no'} | "
            f"{stage['exit_code']} | {stage['duration_seconds']:.3f}s | {summary} |"
        )

    lines.extend(["", "## Dependency audit", ""])
    for name, label in (
        ("npm_audit_production", "Production dependencies (blocking)"),
        ("npm_audit_all", "Complete dependency tree (informational)"),
    ):
        details = report["stages"][name].get("details")
        lines.append(f"### {label}")
        lines.append("")
        if not details:
            lines.append("Structured npm audit output was unavailable; inspect the stage log.")
            lines.append("")
            continue
        severities = ", ".join(f"{key}={value}" for key, value in details["by_severity"].items())
        lines.append(f"Severities: {severities}.")
        lines.append(
            f"Vulnerable dependency packages: direct={details['direct_vulnerable_dependencies']}, "
            f"transitive={details['transitive_vulnerable_dependencies']}."
        )
        if "development_only_by_severity" in details:
            development = ", ".join(
                f"{key}={value}" for key, value in details["development_only_by_severity"].items()
            )
            lines.append(f"Development-only severity delta: {development}.")
            packages = details["development_only_vulnerable_packages"]
            lines.append(
                "Development-only vulnerable packages: "
                + (", ".join(packages) or "none reported")
                + "."
            )
            lines.append(
                "Development delta consistent: "
                + str(details["development_delta_consistent"]).lower()
                + "."
            )
        reported_fixes = details["npm_reported_fixes"]
        major = details["npm_reported_semver_major_fixes"]
        lines.append(
            "npm-reported fixes without a reported semver-major target: "
            + (
                ", ".join(f"{item['name']}@{item['version']}" for item in reported_fixes)
                or "none reported"
            )
            + "."
        )
        lines.append(
            "npm-reported semver-major fixes: "
            + (", ".join(f"{item['name']}@{item['version']}" for item in major) or "none reported")
            + "."
        )
        lines.append("Fix availability is not treated as application compatibility validation.")
        lines.append("")

    python_details = report["stages"]["python_audit"].get("details")
    lines.extend(["### Python production dependencies (informational)", ""])
    if not python_details:
        lines.append("Structured pip-audit output was unavailable; inspect the stage log.")
    else:
        lines.append(
            f"Affected packages: {python_details['vulnerable_dependencies']}; "
            f"unique advisory groups: {python_details['deduplicated_vulnerability_groups']}."
        )
        lines.append(
            "Versions listed by pip-audit are advisory-fixed versions, not automatically "
            "compatible upgrade recommendations."
        )
        for package in python_details["packages"]:
            advisory_fixes = ", ".join(package["advisory_fixed_versions"]) or "none reported"
            lines.append(
                f"- `{package['name']}=={package['version']}`: advisory-fixed versions "
                f"`{advisory_fixes}`; compatible versions validated by this gate: none."
            )
    lines.append("")

    lines.extend(
        [
            "## Evidence",
            "",
            "Per-stage logs are stored beside this report. Logs are referenced by relative path in the JSON report.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    stages = load_results(args.results)
    report_root = args.output_json.parent.parent.parent
    parse_pytest(stages["backend_tests"], report_root)
    parse_pytest(stages["security_tests"], report_root)
    enrich_audits(stages, report_root)

    aggregation = aggregate_results(stages)
    report = {
        "schema_version": 1,
        "commit_sha": args.commit_sha,
        "branch": args.branch,
        "worktree_dirty": args.worktree_dirty == "true",
        "started_at": args.started_at,
        "completed_at": args.completed_at,
        "duration_seconds": round(args.duration_seconds, 3),
        "overall_status": aggregation["overall_status"],
        "overall_exit_code": aggregation["overall_exit_code"],
        "blocking_failures": aggregation["blocking_failures"],
        "missing_stages": aggregation["missing_stages"],
        "compose_project": args.compose_project,
        "release": args.release,
        "stages": stages,
    }
    for stage_name in REQUIRED_STAGE_BLOCKING:
        report[stage_name] = stages[stage_name]

    json_temporary = args.output_json.with_name(f".{args.output_json.name}.tmp")
    markdown_temporary = args.output_markdown.with_name(f".{args.output_markdown.name}.tmp")
    json_temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_temporary.write_text(markdown(report), encoding="utf-8")
    json_temporary.replace(args.output_json)
    markdown_temporary.replace(args.output_markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
