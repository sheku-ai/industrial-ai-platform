from __future__ import annotations

from dataclasses import dataclass
from typing import Any

UNRESOLVED_PROMPT_REF = "unresolved-prompt"


@dataclass(frozen=True)
class PromptResolution:
    """Resolved prompt reference metadata."""

    prompt_ref: str | None
    resolved: bool
    resolver: str = "reference_only_prompt_resolver_v1"
    template_ref: str | None = None
    error_code: str | None = None

    def as_runtime_options(self) -> dict[str, Any]:
        return {
            "prompt_ref": self.prompt_ref,
            "prompt_resolved": self.resolved,
            "prompt_resolver": self.resolver,
            "prompt_template_ref": self.template_ref,
            "prompt_error_code": self.error_code,
        }

    def as_metrics(self) -> dict[str, Any]:
        return self.as_runtime_options()


def resolve_prompt_ref(prompt_ref: str | None) -> PromptResolution:
    """Resolve a prompt reference without introducing a prompt registry dependency."""

    if prompt_ref == UNRESOLVED_PROMPT_REF:
        return PromptResolution(
            prompt_ref=prompt_ref,
            resolved=False,
            template_ref=None,
            error_code="prompt_ref_unresolved",
        )

    return PromptResolution(
        prompt_ref=prompt_ref,
        resolved=True,
        template_ref=prompt_ref or "default-grounded-answer",
    )
