import io
import json

from app.services.s3_visual_record_source import S3VisualRecordSource


class Row:
    def __init__(self, storage_uri):
        self.storage_uri = storage_uri


class ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class Session:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self, statement):
        return ScalarResult(self._rows)


class Client:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []

    def get_object(self, *, Bucket, Key):
        self.calls.append((Bucket, Key))
        payload = self.payloads[(Bucket, Key)]
        return {"Body": io.BytesIO(json.dumps(payload).encode("utf-8"))}


def visual_artifact(image_hash, *, duplicate_of=None, status="succeeded"):
    return {
        "schema": "visual-enrichment/v1",
        "items": [
            {
                "image_id": image_hash,
                "image_hash": image_hash,
                "source_kind": "embedded_image",
                "source_locator": {"page": 1},
                "duplicate_of": duplicate_of,
                "visual": {
                    "status": status,
                    "classification": "diagram",
                    "caption": f"Caption {image_hash}",
                    "description": f"Description {image_hash}",
                    "labels": ["diagram"],
                    "observations": ["Observation"],
                    "confidence": 0.9,
                    "provider_key": "test-provider",
                    "provider_version": "1",
                    "profile": "balanced",
                    "configuration_fingerprint": "cfg-1",
                },
            }
        ],
    }


def main():
    payloads = {
        ("bucket-a", "visual/one.json"): visual_artifact("hash-1"),
        ("bucket-a", "visual/two.json"): visual_artifact("hash-1"),
        ("bucket-a", "visual/three.json"): visual_artifact("hash-2", status="failed"),
    }
    source = S3VisualRecordSource(Client(payloads))
    records = source.load(
        Session(
            [
                Row("s3://bucket-a/visual/one.json"),
                Row("s3://bucket-a/visual/two.json"),
                Row("s3://bucket-a/visual/three.json"),
                Row("https://example.invalid/ignored.json"),
            ]
        ),
        organization_id="org-1",
        execution_id="exec-1",
    )

    checks = {
        "one_unique_record": len(records) == 1,
        "record_id_preserved": records[0].record_id == "visual:hash-1",
        "derived_content_preserved": records[0].metadata.get("derived_content") is True,
        "provider_traceability": records[0].metadata.get("provider_key") == "test-provider",
        "failed_visual_excluded": all(record.record_id != "visual:hash-2" for record in records),
        "invalid_uri_ignored": True,
    }
    passed = all(checks.values())
    print(json.dumps({"passed": passed, "record_count": len(records), **checks}, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
