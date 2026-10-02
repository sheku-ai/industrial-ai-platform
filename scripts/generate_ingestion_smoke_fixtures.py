from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from pypdf import PdfReader, PdfWriter


TEXT_SENTINEL = "SMOKE_TEXT_SENTINEL_25_6A"
PDF_SENTINEL = "SMOKE_PDF_SENTINEL_25_6A"


def create_text_fixture(directory: Path) -> Path:
    path = directory / "sample.txt"
    path.write_text(
        f"{TEXT_SENTINEL}\n\nDeterministic ingestion smoke fixture.\n",
        encoding="utf-8",
    )
    return path


def create_corrupt_pdf(directory: Path) -> Path:
    path = directory / "corrupt.pdf"
    path.write_bytes(b"%PDF-1.7\ncorrupt smoke fixture\n")
    return path


def create_blank_pdf(directory: Path) -> Path:
    path = directory / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/SmokeSentinel": PDF_SENTINEL})
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def create_protected_pdf(source: Path, target: Path, password: str) -> Path:
    reader = PdfReader(str(source))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    if reader.metadata:
        writer.add_metadata({str(key): str(value) for key, value in reader.metadata.items() if value is not None})
    writer.encrypt(password)
    with target.open("wb") as handle:
        writer.write(handle)
    return target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate deterministic ingestion smoke fixtures")
    parser.add_argument("--output-dir", default="tests/fixtures/ingestion")
    parser.add_argument(
        "--source-pdf",
        help="optional text-bearing PDF used to create sample.pdf and protected.pdf",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("SMOKE_PROTECTED_PDF_PASSWORD"),
        help="fixture password; prefer SMOKE_PROTECTED_PDF_PASSWORD",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    directory = Path(args.output_dir)
    directory.mkdir(parents=True, exist_ok=True)

    files = [create_text_fixture(directory), create_corrupt_pdf(directory)]
    if args.source_pdf:
        source = Path(args.source_pdf)
        if not source.is_file():
            raise SystemExit(f"source PDF not found: {source}")
        sample_pdf = directory / "sample.pdf"
        sample_pdf.write_bytes(source.read_bytes())
    else:
        sample_pdf = create_blank_pdf(directory)
    files.append(sample_pdf)

    if args.password:
        files.append(create_protected_pdf(sample_pdf, directory / "protected.pdf", args.password))

    manifest = {
        "text_sentinel": TEXT_SENTINEL,
        "pdf_sentinel": PDF_SENTINEL,
        "files": [str(path) for path in files],
        "protected_fixture_created": bool(args.password),
        "note": "Provide --source-pdf with extractable text for the full PDF content smoke test.",
    }
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
