from __future__ import annotations

import json
from urllib.parse import urlparse

from sqlalchemy import select

from app.models.runtime import RuntimeExecutionArtifact
from app.services.visual_knowledge_records import VisualKnowledgeRecordBuilder


class S3VisualRecordSource:
    def __init__(self, client) -> None:
        self._client = client
        self._builder = VisualKnowledgeRecordBuilder()

    def load(self, session, *, organization_id, execution_id):
        rows = session.scalars(
            select(RuntimeExecutionArtifact)
            .where(
                RuntimeExecutionArtifact.organization_id == organization_id,
                RuntimeExecutionArtifact.execution_id == execution_id,
                RuntimeExecutionArtifact.artifact_type == "visual_enrichment",
                RuntimeExecutionArtifact.status.in_(["published", "verified"]),
            )
            .order_by(RuntimeExecutionArtifact.created_at.asc())
        ).all()

        records = []
        seen = set()
        for row in rows:
            parsed = urlparse(row.storage_uri)
            if parsed.scheme != "s3" or not parsed.netloc:
                continue
            response = self._client.get_object(
                Bucket=parsed.netloc,
                Key=parsed.path.lstrip("/"),
            )
            body = response["Body"]
            try:
                payload = json.loads(body.read().decode("utf-8"))
            finally:
                close = getattr(body, "close", None)
                if callable(close):
                    close()
            if not isinstance(payload, dict):
                continue
            for record in self._builder.build(payload):
                if record.record_id in seen:
                    continue
                seen.add(record.record_id)
                records.append(record)
        return tuple(records)
