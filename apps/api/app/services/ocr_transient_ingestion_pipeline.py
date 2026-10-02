from app.services.transient_ingestion_pipeline import TransientOptionIngestionPipelineCoordinator


class OcrTransientOptionIngestionPipelineCoordinator(TransientOptionIngestionPipelineCoordinator):
    _TRANSIENT_SETTING_KEYS = TransientOptionIngestionPipelineCoordinator._TRANSIENT_SETTING_KEYS | frozenset(
        {
            "enable_ocr",
            "ocr_languages",
            "ocr_dpi",
            "max_ocr_pages",
            "ocr_auto_orient",
            "ocr_grayscale",
            "ocr_contrast_factor",
            "ocr_threshold",
        }
    )
