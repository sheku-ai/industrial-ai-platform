from __future__ import annotations

from dataclasses import replace

from app.services.ingestion_pipeline import IngestionPipelineCoordinator, IngestionPipelineInput


class TransientOptionIngestionPipelineCoordinator(IngestionPipelineCoordinator):
    """Expose approved runtime-only options to adapters without persisting secrets."""

    _TRANSIENT_SETTING_KEYS = frozenset({"document_password", "page_start", "page_end_exclusive"})

    def execute(self, pipeline_input: IngestionPipelineInput, control):
        transient = {
            key: value
            for key, value in pipeline_input.request.options.items()
            if key in self._TRANSIENT_SETTING_KEYS and value is not None
        }
        if not transient:
            return super().execute(pipeline_input, control)

        settings = dict(pipeline_input.configuration.settings)
        settings.update(transient)
        runtime_configuration = replace(
            pipeline_input.configuration,
            settings=settings,
        )
        return super().execute(
            replace(pipeline_input, configuration=runtime_configuration),
            control,
        )
