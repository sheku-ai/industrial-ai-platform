from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.contracts.runtime_execution import (
    GuardrailEvaluationRequest,
    GuardrailEvaluationResult,
)

JsonMapping = Mapping[str, Any]
_DECISION_PRIORITY = {
    "allow": 0,
    "audit_only": 1,
    "warn": 2,
    "fallback": 3,
    "block": 4,
}


@dataclass(frozen=True)
class GuardrailRuleResult:
    rule_id: str
    status: str
    decision: str
    reason: str | None = None
    metadata: JsonMapping = field(default_factory=dict)


@runtime_checkable
class GuardrailRule(Protocol):
    @property
    def rule_id(self) -> str: ...

    @property
    def stages(self) -> Sequence[str]: ...

    def evaluate(self, request: GuardrailEvaluationRequest) -> GuardrailRuleResult: ...


@runtime_checkable
class GuardrailEvaluator(Protocol):
    def evaluate(self, request: GuardrailEvaluationRequest) -> GuardrailEvaluationResult: ...


class DisabledGuardrailEvaluator:
    def evaluate(self, request: GuardrailEvaluationRequest) -> GuardrailEvaluationResult:
        return GuardrailEvaluationResult(
            status="evaluated",
            decision="allow",
            reason="guardrails_disabled",
            rule_results=(),
            metadata={
                "stage": request.stage,
                "rule_count": 0,
                "provider_execution_performed": False,
            },
        )


class DeterministicGuardrailEvaluator:
    def __init__(self, rules: Sequence[GuardrailRule]) -> None:
        self._rules = tuple(sorted(rules, key=lambda rule: rule.rule_id))

    def evaluate(self, request: GuardrailEvaluationRequest) -> GuardrailEvaluationResult:
        applicable = tuple(rule for rule in self._rules if request.stage in set(rule.stages))
        results: list[GuardrailRuleResult] = []
        try:
            for rule in applicable:
                result = rule.evaluate(request)
                if result.decision not in _DECISION_PRIORITY:
                    raise ValueError(f"unsupported guardrail decision: {result.decision}")
                results.append(result)
        except Exception:
            return GuardrailEvaluationResult(
                status="failed",
                decision="fallback",
                reason="guardrail_failed",
                rule_results=tuple(
                    {
                        "rule_id": item.rule_id,
                        "status": item.status,
                        "decision": item.decision,
                        "reason": item.reason,
                    }
                    for item in results
                ),
                metadata={
                    "stage": request.stage,
                    "rule_count": len(applicable),
                    "provider_execution_performed": False,
                },
            )

        winning = max(results, key=lambda item: _DECISION_PRIORITY[item.decision], default=None)
        decision = winning.decision if winning else "allow"
        reason = winning.reason if winning else "no_applicable_rules"
        return GuardrailEvaluationResult(
            status="evaluated",
            decision=decision,
            reason=reason,
            rule_results=tuple(
                {
                    "rule_id": item.rule_id,
                    "status": item.status,
                    "decision": item.decision,
                    "reason": item.reason,
                    "metadata": dict(item.metadata),
                }
                for item in results
            ),
            metadata={
                "stage": request.stage,
                "rule_count": len(results),
                "provider_execution_performed": False,
            },
        )
