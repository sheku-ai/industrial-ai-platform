from __future__ import annotations

import sys
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.contracts.runtime_execution import ProviderExecutionResult
from app.orchestration.normalization import (
    NormalizedResponseStatus,
    ProviderResponseNormalizer,
)


def main() -> None:
    normalizer = ProviderResponseNormalizer()

    completed = normalizer.normalize(
        ProviderExecutionResult(
            request_id=uuid.uuid4(),
            status="success",
            output_text="  normalized answer  ",
            finish_reason="STOP",
            usage={"prompt_tokens": 10, "completion_tokens": 4},
            latency_ms=25,
            provider_metadata={"region": "local", "api_key": "forbidden"},
        )
    )
    assert completed.status == NormalizedResponseStatus.COMPLETED
    assert completed.text == "normalized answer"
    assert completed.finish_reason == "stop"
    assert completed.usage == {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14}
    assert "api_key" not in completed.metadata

    empty = normalizer.normalize(
        ProviderExecutionResult(
            request_id=uuid.uuid4(),
            status="completed",
            output_text="   ",
        )
    )
    assert empty.status == NormalizedResponseStatus.EMPTY
    assert empty.error_code == "provider_empty_response"

    failed = normalizer.normalize(
        ProviderExecutionResult(
            request_id=uuid.uuid4(),
            status="failed",
            retryable=True,
            provider_error_code="RATE_LIMITED",
            output_text="must not leak",
            usage={"total_tokens": "invalid", "input_tokens": -1},
        )
    )
    assert failed.status == NormalizedResponseStatus.FAILED
    assert failed.text is None
    assert failed.retryable is True
    assert failed.error_code == "rate_limited"
    assert failed.usage == {}

    print({
        "status": "passed",
        "response_normalization": True,
        "success_status_normalized": True,
        "empty_response_detected": True,
        "failure_status_normalized": True,
        "usage_normalized": True,
        "sensitive_metadata_removed": True,
        "provider_execution_performed": False,
        "network_call_performed": False,
        "generation_performed": False,
    })


if __name__ == "__main__":
    main()
