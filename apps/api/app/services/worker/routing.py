"""Generic job routing for Platform Worker."""

from __future__ import annotations

from app.services.worker.contracts import JobLease, WorkerNodeRef
from app.services.worker.interfaces import JobRoutingService


class CapabilityJobRoutingService(JobRoutingService):
    """Routes jobs using generic capabilities.

    Routing is based on job type, pipeline name, and adapter profile hints. It
    must not encode customer, country, location, plant, asset, department, or
    fixed document taxonomy assumptions.
    """

    def can_execute(self, worker: WorkerNodeRef, lease: JobLease) -> bool:
        capabilities = set(worker.capabilities)

        if "*" in capabilities:
            return True

        accepted = {
            lease.job_type,
            f"job:{lease.job_type}",
        }

        if lease.pipeline_name:
            accepted.add(f"pipeline:{lease.pipeline_name}")

        adapter_name = lease.adapter_profile.get("adapter_name")
        if isinstance(adapter_name, str) and adapter_name:
            accepted.add(f"adapter:{adapter_name}")

        return bool(capabilities.intersection(accepted))
