import json
import threading
import time
import uuid

from app.services.cached_visual_enrichment_producer import CachedVisualEnrichmentProducer
from app.services.duplicate_work_cache import BoundedDuplicateWorkCache
from app.services.multimodal_contracts import (
    CapabilityState,
    ProcessingProfile,
    ProviderCapability,
    VisualUnderstandingRequest,
)
from app.services.visual_understanding import visual_cache_key


class Handle:
    def __init__(self, checksum):
        self.checksum_sha256 = checksum
        self.detected_media_type = "application/pdf"


class Acquisition:
    def __init__(self, checksum):
        self.checksum = checksum
        self.calls = 0

    def open_handle(self, source_reference):
        self.calls += 1
        return Handle(self.checksum)


class Delegate:
    def __init__(self):
        self.calls = 0
        self.lock = threading.Lock()

    def produce(self, item, heartbeat):
        with self.lock:
            self.calls += 1
            call = self.calls
        time.sleep(0.05)
        return {"schema": "visual-enrichment/v1", "call": call}


class Item:
    def __init__(self, organization_id, *, options=None):
        self.organization_id = organization_id
        self.input_payload = {
            "source_reference": "s3://bucket/source.pdf",
            "declared_media_type": "application/pdf",
            "options": options or {},
        }
        self.policy_snapshot = {}


def main():
    organization_id = uuid.uuid4()
    delegate = Delegate()
    acquisition = Acquisition("a" * 64)
    cache = BoundedDuplicateWorkCache(max_entries=2, ttl_seconds=30)
    producer = CachedVisualEnrichmentProducer(delegate, acquisition, cache=cache)
    item = Item(organization_id)

    results = []

    def run():
        results.append(producer.produce(item, object()))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    first_metrics = producer.metrics()
    repeated = producer.produce(item, object())
    different_configuration = producer.produce(
        Item(organization_id, options={"visual_understanding": {"profile": "high_fidelity"}}),
        object(),
    )
    different_organization = producer.produce(Item(uuid.uuid4()), object())

    no_checksum_delegate = Delegate()
    no_checksum_producer = CachedVisualEnrichmentProducer(
        no_checksum_delegate,
        Acquisition(None),
        cache=BoundedDuplicateWorkCache(max_entries=2, ttl_seconds=30),
    )
    no_checksum_item = Item(organization_id)
    no_checksum_producer.produce(no_checksum_item, object())
    no_checksum_producer.produce(no_checksum_item, object())

    bounded = BoundedDuplicateWorkCache(max_entries=2, ttl_seconds=30)
    bounded.get_or_compute("one", lambda: 1)
    bounded.get_or_compute("two", lambda: 2)
    bounded.get_or_compute("three", lambda: 3)
    bounded_metrics = bounded.metrics()

    capability = ProviderCapability(
        provider_key="provider",
        capability="image_understanding",
        state=CapabilityState.AVAILABLE,
        version="1",
        local=True,
        requires_gpu=False,
        details={},
    )
    request = VisualUnderstandingRequest(
        profile=ProcessingProfile.BALANCED,
        prompt="Describe",
        configuration={"mode": "deterministic"},
        timeout_seconds=1,
    )
    image_key_one = visual_cache_key("image-hash", capability, request)
    image_key_two = visual_cache_key("image-hash", capability, request)
    image_key_changed = visual_cache_key(
        "different-image-hash",
        capability,
        request,
    )

    checks = {
        "concurrent_duplicate_computed_once": delegate.calls == 3,
        "concurrent_callers_received_same_artifact": len(results) == 2 and results[0] == results[1],
        "shared_active_work_observed": first_metrics["duplicate_cache_shared_active"] == 1,
        "sequential_checksum_cache_hit": repeated == results[0],
        "configuration_isolates_cache_key": different_configuration["call"] == 2,
        "organization_isolates_cache_key": different_organization["call"] == 3,
        "missing_checksum_bypasses_cache": no_checksum_delegate.calls == 2,
        "bounded_cache_evicts": bounded_metrics["duplicate_cache_entries"] == 2
        and bounded_metrics["duplicate_cache_evictions"] == 1,
        "image_hash_key_is_stable": image_key_one == image_key_two,
        "image_hash_changes_cache_key": image_key_one != image_key_changed,
        "cache_returns_copies": results[0] is not results[1],
    }
    passed = all(checks.values())
    print(json.dumps({"passed": passed, **checks}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
