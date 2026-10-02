import hashlib
import io
import json
import tempfile
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from app.services.ingestion_adapter_resolver import DeploymentEdition, IngestionAdapterResolver
from app.services.ingestion_adapters.segmented_pdf import SegmentedPdfIngestionAdapter
from app.services.ingestion_contracts import AcquiredSource, IngestionRequest, ResolvedAdapterConfiguration
from app.services.ingestion_pipeline import IngestionPipelineInput
from app.services.ocr_transient_ingestion_pipeline import OcrTransientOptionIngestionPipelineCoordinator


class Control:
    def pulse(self):
        pass

    def checkpoint(self):
        pass

    def raise_if_cancellation_requested(self):
        pass

    def is_cancellation_requested(self):
        return False


def make_pdf():
    image = Image.new("RGB", (1200, 400), "white")
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 70)
    ImageDraw.Draw(image).text((50, 140), "POLICY OCR 257", fill="black", font=font)
    png = io.BytesIO()
    image.save(png, format="PNG")
    png.seek(0)
    out = io.BytesIO()
    pdf = canvas.Canvas(out, pagesize=letter)
    pdf.drawImage(ImageReader(png), 40, 300, width=520, height=173, preserveAspectRatio=True)
    pdf.showPage()
    pdf.save()
    return out.getvalue()


def run(path, data, options):
    org, doc, ver, exe, profile = [uuid4() for _ in range(5)]
    req = IngestionRequest(
        organization_id=org,
        execution_id=exe,
        subject_type="document_version",
        subject_id=ver,
        document_id=doc,
        document_version_id=ver,
        source_reference="file://scan.pdf",
        declared_media_type="application/pdf",
        original_file_name="scan.pdf",
        content_length=len(data),
        checksum_sha256=hashlib.sha256(data).hexdigest(),
        pipeline_profile_id=profile,
        adapter_hint="platform.pdf.text_layer",
        options=options,
    )
    src = AcquiredSource(
        source_reference=req.source_reference,
        local_path=str(path),
        detected_media_type="application/pdf",
        content_length=len(data),
        checksum_sha256=req.checksum_sha256,
    )
    cfg = ResolvedAdapterConfiguration(
        adapter_key="platform.pdf.text_layer",
        adapter_version="1.0.0",
        pipeline_profile_revision="1",
        settings={"max_pages": 10},
    )
    pipe = OcrTransientOptionIngestionPipelineCoordinator(IngestionAdapterResolver([SegmentedPdfIngestionAdapter()]))
    return pipe.execute(
        IngestionPipelineInput(
            request=req, source=src, configuration=cfg, deployment_edition=DeploymentEdition.COMMUNITY
        ),
        Control(),
    ).extraction


def main():
    data = make_pdf()
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "scan.pdf"
        path.write_bytes(data)
        disabled = False
        try:
            run(path, data, {})
        except Exception as exc:
            disabled = "OCR capability is not configured" in str(exc)
        result = run(
            path, data, {"enable_ocr": True, "max_ocr_pages": 1, "ocr_languages": "eng", "ocr_auto_orient": False}
        )
    unit = result.content_units[0]
    metrics = dict(result.metrics)
    text = (unit.text or "").upper()
    checks = {
        "disabled_path_preserved": disabled,
        "enabled_path_succeeded": len(result.content_units) == 1,
        "sentinel_found": "POLICY" in text and "257" in text,
        "page_provenance": unit.source_locator.get("page_number") == 1,
        "ocr_attribute": unit.attributes.get("ocr") is True,
        "ocr_used_metric": metrics.get("ocr_used") is True,
        "ocr_page_limit_respected": metrics.get("ocr_pages_processed") == 1 and metrics.get("max_ocr_pages") == 1,
        "detected_format": result.detected_format == "pdf_ocr_enriched",
    }
    passed = all(checks.values())
    print(
        json.dumps(
            {"passed": passed, "recognized_text": unit.text, "metrics": metrics, **checks}, indent=2, sort_keys=True
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
