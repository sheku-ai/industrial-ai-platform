#!/usr/bin/env python3
"""Consolidated Sprint 12 runtime smoke validation.

This orchestrates the Sprint 12 smoke suite and emits one runtime summary for
closure readiness. It does not require external LLMs, GPU, embeddings, BGE,
Qdrant, or any non-deterministic provider.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Callable

from smoke_answer_mode_contract import run_smoke as run_answer_mode_contract
from smoke_assisted_answer_runtime import run_smoke as run_assisted_answer_runtime
from smoke_fallback_error_semantics import run_smoke as run_fallback_error_semantics
from smoke_inference_provider_abstraction import run_smoke as run_inference_provider_abstraction
from smoke_knowledge_runtime import SmokeFailure, run_smoke as run_knowledge_runtime
from smoke_prompt_guardrail_references import run_smoke as run_prompt_guardrail_references


SmokeRunner = Callable[[str, str], dict[str, Any]]


def _run_case(name: str, runner: SmokeRunner, base_url: str, query_text: str) -> dict[str, Any]:
    result = runner(base_url, query_text)
    if result.get("status") != "passed":
        raise SmokeFailure(f"{name} did not return passed status")
    return result


def run_smoke(base_url: str, query_text: str) -> dict[str, Any]:
    cases: tuple[tuple[str, SmokeRunner], ...] = (
        ("knowledge_runtime", run_knowledge_runtime),
        ("answer_mode_contract", run_answer_mode_contract),
        ("inference_provider_abstraction", run_inference_provider_abstraction),
        ("prompt_guardrail_references", run_prompt_guardrail_references),
        ("assisted_answer_runtime", run_assisted_answer_runtime),
        ("fallback_error_semantics", run_fallback_error_semantics),
    )

    results: dict[str, dict[str, Any]] = {}
    for name, runner in cases:
        results[name] = _run_case(name, runner, base_url, query_text)

    knowledge = results["knowledge_runtime"]
    assisted = results["assisted_answer_runtime"]
    fallback = results["fallback_error_semantics"]

    return {
        "status": "passed",
        "sprint": "12.6",
        "validation": "sprint_12_runtime_consolidated",
        "case_count": len(results),
        "cases": {name: result.get("status") for name, result in results.items()},
        "runtime_baseline": {
            "retrieval_provider": knowledge.get("retrieval_provider"),
            "query_normalized": knowledge.get("query_normalized"),
            "highlighting_enabled": knowledge.get("highlighting_enabled"),
            "facets_enabled": knowledge.get("facets_enabled"),
            "reranking_enabled": knowledge.get("reranking_enabled"),
            "extractive_answer_enabled": knowledge.get("extractive_answer_enabled"),
            "query_metrics_enabled": knowledge.get("query_metrics_enabled"),
            "query_text_recorded": knowledge.get("query_text_recorded"),
        },
        "answer_modes": {
            "context_only": results["answer_mode_contract"].get("context_only_mode"),
            "extractive": results["answer_mode_contract"].get("extractive_mode"),
            "assisted_success": assisted.get("resolved_answer_mode"),
            "assisted_fallback": results["answer_mode_contract"].get("assisted_resolved_mode"),
        },
        "assisted_success": {
            "answer_generated": assisted.get("answer_generated"),
            "llm_used": assisted.get("llm_used"),
            "fallback_used": assisted.get("fallback_used"),
            "inference_provider_adapter": assisted.get("inference_provider_adapter"),
            "assisted_generation_strategy": assisted.get("assisted_generation_strategy"),
        },
        "fallback_semantics": {
            "provider_failed": fallback.get("provider_failed"),
            "provider_timeout": fallback.get("provider_timeout"),
            "prompt_ref_unresolved": fallback.get("prompt_ref_unresolved"),
            "guardrail_blocked": fallback.get("guardrail_blocked"),
            "answer_generated": fallback.get("answer_generated"),
            "llm_used": fallback.get("llm_used"),
        },
        "governance": {
            "feedback_received": knowledge.get("feedback_received"),
            "feedback_persistence_enabled": knowledge.get("feedback_persistence_enabled"),
            "citation_count": knowledge.get("citation_count"),
            "context_count": knowledge.get("context_count"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run consolidated Sprint 12 runtime smoke validation.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--query", default="PostgreSQL source of truth")
    args = parser.parse_args()

    try:
        result = run_smoke(args.base_url, args.query)
    except SmokeFailure as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
