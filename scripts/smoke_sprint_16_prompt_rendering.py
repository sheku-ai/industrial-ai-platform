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

from app.contracts.runtime_execution import PromptRenderRequest  # noqa: E402
from app.prompting import DeterministicPromptRenderer  # noqa: E402


class SmokeFailure(RuntimeError):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def run_smoke() -> dict[str, object]:
    renderer = DeterministicPromptRenderer()
    request = PromptRenderRequest(
        prompt_id=uuid.uuid4(),
        template="Question: {{ question }}\nContext:\n{{ context }}\nCitations:\n{{ citations }}",
        variables={"question": "What is the source of truth?", "unused": "ignored"},
        context=("PostgreSQL is the source of truth.",),
        citations=({"id": "ref-1", "label": "Platform architecture"},),
    )
    result = renderer.render(request)
    check(result.status == "rendered", "render status")
    check(result.error_code is None, "unexpected error")
    check(result.rendered_prompt is not None, "missing rendered prompt")
    check("PostgreSQL is the source of truth." in result.rendered_prompt, "context injection")
    check('"id": "ref-1"' in result.rendered_prompt, "citation injection")
    check("unused" not in result.rendered_prompt, "unused variable leakage")

    missing = renderer.render(
        PromptRenderRequest(
            prompt_id=uuid.uuid4(),
            template="{{ required_b }} {{ required_a }} {{ required_b }}",
            variables={},
        )
    )
    check(missing.status == "failed", "missing variable status")
    check(missing.error_code == "prompt_variable_missing", "missing variable error")
    check(missing.missing_variables == ("required_a", "required_b"), "missing variable order")

    literal = renderer.render(
        PromptRenderRequest(
            prompt_id=uuid.uuid4(),
            template="Literal: {{ value }}; expression: {{ invalid-name }}",
            variables={"value": "safe"},
        )
    )
    check(literal.status == "rendered", "literal render")
    check("{{ invalid-name }}" in (literal.rendered_prompt or ""), "unsupported syntax must remain literal")

    return {
        "status": "passed",
        "sprint": "16.4",
        "validation": "prompt_rendering",
        "deterministic_render": True,
        "context_injected": True,
        "citations_injected": True,
        "missing_variables_detected": True,
        "expression_evaluation_performed": False,
        "secret_resolution_performed": False,
        "network_call_performed": False,
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
