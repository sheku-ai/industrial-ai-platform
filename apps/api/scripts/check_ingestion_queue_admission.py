import json
from types import SimpleNamespace

from app.services.ingestion_queue_admission import IngestionQueueAdmission, IngestionQueuePolicy


def main():
    admission = IngestionQueueAdmission(
        IngestionQueuePolicy(
            heavy_bytes_threshold=100,
            heavy_pages_threshold=10,
            max_consecutive_heavy=1,
        )
    )
    normal = SimpleNamespace(input_payload={"content_length": 10, "options": {"page_count_hint": 2}})
    heavy_size = SimpleNamespace(input_payload={"content_length": 100, "options": {"page_count_hint": 2}})
    heavy_pages = SimpleNamespace(input_payload={"content_length": 10, "options": {"page_count_hint": 10}})
    heavy_ocr = SimpleNamespace(
        input_payload={"content_length": 10, "options": {"page_count_hint": 2, "requires_ocr_hint": True}}
    )

    selected_heavy, heavy_lane = admission.choose([heavy_size])
    selected_normal, normal_lane = admission.choose([heavy_pages, normal])

    checks = {
        "normal_classified": admission.classify(normal.input_payload) == "normal",
        "heavy_size_classified": admission.classify(heavy_size.input_payload) == "heavy",
        "heavy_pages_classified": admission.classify(heavy_pages.input_payload) == "heavy",
        "heavy_ocr_classified": admission.classify(heavy_ocr.input_payload) == "heavy",
        "heavy_selected_when_alone": selected_heavy is heavy_size and heavy_lane == "heavy",
        "normal_selected_after_heavy": selected_normal is normal and normal_lane == "normal",
    }
    passed = all(checks.values())
    print(json.dumps({"passed": passed, **checks}, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
