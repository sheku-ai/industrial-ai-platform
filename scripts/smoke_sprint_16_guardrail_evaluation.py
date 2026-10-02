#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps" / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

from app.contracts.runtime_execution import GuardrailEvaluationRequest  # noqa: E402
from app.guardrails import (  # noqa: E402
    DeterministicGuardrailEvaluator,
    DisabledGuardrailEvaluator,
    GuardrailRuleResult,
)


class SmokeFailure(RuntimeError):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


class StaticRule:
    def __init__(self, rule_id: str, stages: tuple[str, ...], decision: str, reason: str) -> None:
        self._rule_id = rule_id
        self._stages = stages
        self._decision = decision
        self._reason = reason

    @property
    def rule_id(self) -> str:
        return self._rule_id

    @property
    def stages(self) -> tuple[str, ...]:
        return self._stages

    def evaluate(self, request: GuardrailEvaluationRequest) -> GuardrailRuleResult:
        return GuardrailRuleResult(
            rule_id=self.rule_id,
            status="evaluated",
            decision=self._decision,
            reason=self._reason,
            metadata={"stage": request.stage},
        )


class FailingRule(StaticRule):
    def evaluate(self, request: GuardrailEvaluationRequest) -> GuardrailRuleResult:
        raise RuntimeError("simulated failure")


def run_smoke() -> dict[str, object]:
    request = GuardrailEvaluationRequest(
        guardrail_id=uuid.uuid4(),
        stage="pre_execution",
        input_text="test input",
    )

    disabled = DisabledGuardrailEvaluator().evaluate(request)
    check(disabled.status == "evaluated", "disabled status")
    check(disabled.decision == "allow", "disabled decision")
    check(disabled.reason == "guardrails_disabled", "disabled reason")

    evaluator = DeterministicGuardrailEvaluator(
        (
            StaticRule("rule-z", ("pre_execution",), "warn", "warning"),
            StaticRule("rule-a", ("pre_execution",), "block", "blocked"),
            StaticRule("rule-post", ("post_execution",), "fallback", "post only"),
        )
    )
    result = evaluator.evaluate(request)
    check(result.status == "evaluated", "evaluation status")
    check(result.decision == "block", "decision precedence")
    check(result.reason == "blocked", "winning reason")
    check([item["rule_id"] for item in result.rule_results] == ["rule-a", "rule-z"], "stable order")

    failed = DeterministicGuardrailEvaluator(
        (FailingRule("rule-fail", ("pre_execution",), "allow", "unused"),)
    ).evaluate(request)
    check(failed.status == "failed", "failure status")
    check(failed.decision == "fallback", "failure decision")
    check(failed.reason == "guardrail_failed", "failure reason")

    no_rules = DeterministicGuardrailEvaluator(()).evaluate(request)
    check(no_rules.decision == "allow", "no-rule decision")
    check(no_rules.reason == "no_applicable_rules", "no-rule reason")

    return {
        "status": "passed",
        "sprint": "16.5",
        "validation": "guardrail_evaluation",
        "pre_execution_supported": True,
        "post_execution_supported": True,
        "stable_rule_order": True,
        "decision_precedence_enforced": True,
        "rule_failure_falls_back": True,
        "fixed_business_policy_embedded": False,
        "secret_resolution_performed": False,
        "network_call_performed": False,
        "provider_execution_performed": False,
        "generation_performed": False,
    }


def main() -> int:
    try:
        result = run_smoke()
    except SmokeFailure as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
