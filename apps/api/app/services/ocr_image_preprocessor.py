from __future__ import annotations

import io
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps


@dataclass(frozen=True)
class OcrPreprocessingResult:
    payload: bytes
    width: int
    height: int
    rotation_degrees: int
    grayscale: bool
    contrast_factor: float
    threshold: int | None


class OcrImagePreprocessor:
    def __init__(
        self,
        *,
        tesseract_executable: str = "tesseract",
        orientation_timeout_seconds: int = 10,
    ) -> None:
        if orientation_timeout_seconds <= 0:
            raise ValueError("orientation_timeout_seconds must be positive")
        self.tesseract_executable = tesseract_executable
        self.orientation_timeout_seconds = orientation_timeout_seconds

    def preprocess(
        self,
        payload: bytes,
        *,
        auto_orient: bool = True,
        grayscale: bool = True,
        contrast_factor: float = 1.5,
        threshold: int | None = None,
    ) -> OcrPreprocessingResult:
        if not payload:
            raise ValueError("image payload cannot be empty")
        if contrast_factor <= 0:
            raise ValueError("contrast_factor must be positive")
        if threshold is not None and not 0 <= threshold <= 255:
            raise ValueError("threshold must be between zero and 255")

        try:
            image = Image.open(io.BytesIO(payload))
            image.load()
        except Exception as exc:
            raise ValueError("image payload could not be decoded") from exc

        rotation = self.detect_orientation(payload) if auto_orient else 0
        if rotation:
            image = image.rotate(rotation, expand=True, fillcolor="white")
        if grayscale:
            image = ImageOps.grayscale(image)
        image = ImageOps.autocontrast(image)
        if contrast_factor != 1.0:
            image = ImageEnhance.Contrast(image).enhance(contrast_factor)
        if threshold is not None:
            if image.mode != "L":
                image = ImageOps.grayscale(image)
            image = image.point(lambda value: 255 if value >= threshold else 0, mode="1").convert("L")

        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
        return OcrPreprocessingResult(
            payload=output.getvalue(),
            width=image.width,
            height=image.height,
            rotation_degrees=rotation,
            grayscale=grayscale,
            contrast_factor=contrast_factor,
            threshold=threshold,
        )

    def detect_orientation(self, payload: bytes) -> int:
        with tempfile.TemporaryDirectory(prefix="industrial-ai-osd-") as workspace:
            source = Path(workspace) / "source.png"
            source.write_bytes(payload)
            try:
                completed = subprocess.run(
                    [self.tesseract_executable, str(source), "stdout", "--psm", "0"],
                    capture_output=True,
                    text=True,
                    timeout=self.orientation_timeout_seconds,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                return 0
            combined = f"{completed.stdout}\n{completed.stderr}"
            match = re.search(r"Rotate:\s*(0|90|180|270)", combined)
            if match is None:
                return 0
            rotate_clockwise = int(match.group(1))
            return (-rotate_clockwise) % 360
