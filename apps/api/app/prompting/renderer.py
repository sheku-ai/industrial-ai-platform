from __future__ import annotations

import json
import re
from typing import Protocol, runtime_checkable

from app.contracts.runtime_execution import PromptRenderRequest, PromptRenderResult

_PLACEHOLDER = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")


@runtime_checkable
class PromptRenderer(Protocol):
    def render(self, request: PromptRenderRequest) -> PromptRenderResult: ...


class DeterministicPromptRenderer:
    def render(self, request: PromptRenderRequest) -> PromptRenderResult:
        try:
            reserved = {
                "context": "\n".join(request.context),
                "citations": "\n".join(
                    json.dumps(dict(item), sort_keys=True, ensure_ascii=False) for item in request.citations
                ),
            }
            values = {str(key): str(value) for key, value in request.variables.items()}
            values.update(reserved)

            required = tuple(sorted(set(_PLACEHOLDER.findall(request.template))))
            missing = tuple(name for name in required if name not in values)
            if missing:
                return PromptRenderResult(
                    status="failed",
                    rendered_prompt=None,
                    missing_variables=missing,
                    error_code="prompt_variable_missing",
                    metadata={"required_variable_count": len(required)},
                )

            rendered = _PLACEHOLDER.sub(lambda match: values[match.group(1)], request.template)
            return PromptRenderResult(
                status="rendered",
                rendered_prompt=rendered,
                missing_variables=(),
                error_code=None,
                metadata={
                    "required_variable_count": len(required),
                    "context_item_count": len(request.context),
                    "citation_count": len(request.citations),
                    "provider_execution_performed": False,
                },
            )
        except Exception:
            return PromptRenderResult(
                status="failed",
                rendered_prompt=None,
                missing_variables=(),
                error_code="prompt_render_failed",
                metadata={"provider_execution_performed": False},
            )
