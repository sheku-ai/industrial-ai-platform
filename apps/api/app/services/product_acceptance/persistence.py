from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from app.services.product_acceptance.contracts import AcceptanceIdentity, utc_now
from app.services.product_acceptance.gateway import AcceptanceHttpClient


class AcceptanceEvidenceClient:
    def __init__(self, http: AcceptanceHttpClient, identity: AcceptanceIdentity) -> None:
        self.http = http
        self.identity = identity
        self.available = False
        self.failures: list[dict[str, Any]] = []

    @contextmanager
    def _platform_scope(self) -> Iterator[None]:
        original_scope = self.http.authorization_scope
        original_organization_id = self.http.organization_id
        self.http.set_platform_scope()
        try:
            yield
        finally:
            if original_scope == "organization" and original_organization_id:
                self.http.set_organization_scope(original_organization_id)
            elif original_scope == "platform":
                self.http.set_platform_scope()
            else:
                self.http.authorization_scope = original_scope
                self.http.organization_id = original_organization_id

    def create_execution(self, preserve: bool, reuse: bool, cleanup: bool) -> None:
        organization_id = self.http.organization_id
        with self._platform_scope():
            result = self.http.post(
                "/product-acceptance/executions",
                {
                    "execution_key": self.identity.execution_key,
                    "correlation_id": self.identity.correlation_id,
                    "scenario": "local_product_acceptance",
                    "status": "RUNNING",
                    "started_at": utc_now(),
                    "organization_id": organization_id,
                    "preserve_requested": preserve,
                    "reuse_requested": reuse,
                    "cleanup_requested": cleanup,
                    "report": {},
                    "warnings": [],
                    "blockers": [],
                },
            )
        self.available = result.ok
        if not result.ok:
            self.failures.append({"operation": "create_execution", "error": result.error, "details": result.data})

    def gate(self, payload: dict[str, Any]) -> bool:
        if self.available:
            with self._platform_scope():
                result = self.http.post(
                    f"/product-acceptance/executions/{self.identity.execution_key}/gates",
                    payload,
                )
            if not result.ok:
                self.failures.append(
                    {"operation": "gate", "payload": payload, "error": result.error, "details": result.data}
                )
            return result.ok
        return False

    def resource(self, payload: dict[str, Any]) -> bool:
        if self.available:
            with self._platform_scope():
                result = self.http.post(
                    f"/product-acceptance/executions/{self.identity.execution_key}/resources",
                    payload,
                )
            if not result.ok:
                self.failures.append(
                    {"operation": "resource", "payload": payload, "error": result.error, "details": result.data}
                )
            return result.ok
        return False

    def finish(self, payload: dict[str, Any]) -> bool:
        if self.available:
            with self._platform_scope():
                result = self.http.patch(
                    f"/product-acceptance/executions/{self.identity.execution_key}",
                    payload,
                )
            if not result.ok:
                self.failures.append({"operation": "finish", "error": result.error, "details": result.data})
            return result.ok
        return False

    def finalize_execution_best_effort(self, payload: dict[str, Any]) -> bool:
        return self.finish(payload)
