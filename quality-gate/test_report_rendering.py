#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

SPEC = importlib.util.spec_from_file_location(
    "quality_gate_report_renderer", SCRIPTS / "render-quality-report.py"
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable to load Quality Gate report renderer")
RENDERER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RENDERER)


def npm_payload(names: list[str]) -> dict[str, object]:
    vulnerabilities = {
        name: {
            "name": name,
            "severity": "high",
            "isDirect": name == "next",
            "range": "<1.1.18",
            "via": [
                {
                    "source": index,
                    "name": name,
                    "title": f"{name} advisory",
                    "severity": "high",
                    "range": "<1.1.18",
                    "url": f"https://github.com/advisories/GHSA-{index:04d}",
                }
            ],
            "fixAvailable": True,
        }
        for index, name in enumerate(names, start=1)
    }
    return {
        "metadata": {
            "vulnerabilities": {
                "info": 0,
                "low": 0,
                "moderate": 0,
                "high": len(names),
                "critical": 0,
                "total": len(names),
            }
        },
        "vulnerabilities": vulnerabilities,
    }


class QualityGateReportRenderingTests(unittest.TestCase):
    def test_complete_audit_explicitly_includes_development_dependencies(self) -> None:
        runner = (ROOT / "quality-gate" / "run-quality-gate.sh").read_text(encoding="utf-8")
        self.assertIn("npm audit --include=dev --audit-level=high --json", runner)

    def test_development_delta_uses_package_set_and_exact_severity_subtraction(self) -> None:
        production = RENDERER.audit_details(
            npm_payload(["nanoid", "next", "postcss", "sharp"]), {}
        )
        complete = RENDERER.audit_details(
            npm_payload(
                ["brace-expansion", "js-yaml", "nanoid", "next", "postcss", "sharp"]
            ),
            {},
        )

        delta = RENDERER.development_audit_delta(production, complete)

        self.assertEqual(
            delta["development_only_vulnerable_packages"], ["brace-expansion", "js-yaml"]
        )
        self.assertEqual(delta["development_only_by_severity"]["high"], 2)
        self.assertTrue(delta["development_delta_consistent"])

    def test_boolean_npm_fix_does_not_claim_compatibility(self) -> None:
        details = RENDERER.audit_details(
            npm_payload(["brace-expansion"]), {"brace-expansion": ["1.1.15"]}
        )
        package = details["vulnerable_packages"][0]

        self.assertIsNone(package["fix_without_semver_major"])
        self.assertEqual(package["compatibility_status"], "not_validated")
        self.assertEqual(details["npm_reported_fixes"][0]["version"], "target not reported")

    def test_pip_audit_fix_versions_are_not_compatible_upgrade_claims(self) -> None:
        details = RENDERER.pip_audit_details(
            [
                {
                    "name": "starlette",
                    "version": "0.41.3",
                    "vulns": [
                        {
                            "id": "PYSEC-EXAMPLE",
                            "aliases": ["CVE-EXAMPLE", "GHSA-EXAMPLE"],
                            "fix_versions": ["0.47.2"],
                        }
                    ],
                }
            ]
        )
        package = details["packages"][0]

        self.assertEqual(package["advisory_fixed_versions"], ["0.47.2"])
        self.assertEqual(package["validated_compatible_versions"], [])
        self.assertEqual(package["compatibility_status"], "not_validated_by_pip_audit")
        self.assertEqual(
            details["version_interpretation"],
            "advisory_fixes_only_not_compatibility_validated",
        )

    def test_markdown_renders_dev_delta_and_compatibility_disclaimer(self) -> None:
        stages = {
            name: {
                "status": "passed",
                "blocking": blocking,
                "exit_code": 0,
                "duration_seconds": 0.0,
                "summary": name,
                "log": f"{name}.log",
            }
            for name, blocking in RENDERER.REQUIRED_STAGE_BLOCKING.items()
        }
        production = RENDERER.audit_details(npm_payload(["next"]), {})
        complete = RENDERER.audit_details(
            npm_payload(["brace-expansion", "js-yaml", "next"]), {}
        )
        complete.update(RENDERER.development_audit_delta(production, complete))
        stages["npm_audit_production"]["details"] = production
        stages["npm_audit_all"]["details"] = complete
        stages["python_audit"]["details"] = RENDERER.pip_audit_details(
            [
                {
                    "name": "starlette",
                    "version": "0.41.3",
                    "vulns": [
                        {"id": "PYSEC-EXAMPLE", "aliases": [], "fix_versions": ["0.47.2"]}
                    ],
                }
            ]
        )
        report = {
            "overall_status": "passed",
            "overall_exit_code": 0,
            "commit_sha": "test-sha",
            "branch": "test",
            "worktree_dirty": True,
            "compose_project": "industrial-ai-quality",
            "release": False,
            "started_at": "2026-01-01T00:00:00Z",
            "completed_at": "2026-01-01T00:00:01Z",
            "duration_seconds": 1.0,
            "stages": stages,
        }

        rendered = RENDERER.markdown(report)

        self.assertIn("Development-only vulnerable packages: brace-expansion, js-yaml.", rendered)
        self.assertIn("not automatically compatible upgrade recommendations", rendered)
        self.assertIn("compatible versions validated by this gate: none", rendered)


if __name__ == "__main__":
    unittest.main()
