from __future__ import annotations

import mimetypes
import posixpath
import re
import zipfile
from io import BytesIO
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET

from app.services.embedded_image_builder import EmbeddedImageBuilder
from app.services.embedded_image_extraction import EmbeddedImageExtractionResult

_REL_NS = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}


class OoxmlEmbeddedImageExtractor:
    def __init__(self, *, min_width: int = 32, min_height: int = 32, max_images: int = 500) -> None:
        self.min_width = min_width
        self.min_height = min_height
        self.max_images = max_images

    def extract(self, payload: bytes, *, source_kind: str) -> EmbeddedImageExtractionResult:
        if source_kind not in {"docx", "pptx", "xlsx"}:
            raise ValueError("source_kind must be docx, pptx or xlsx")
        builder = EmbeddedImageBuilder(min_width=self.min_width, min_height=self.min_height)
        occurrences = []
        skipped = 0
        with zipfile.ZipFile(BytesIO(payload)) as package:
            for media_path, locator, metadata in self._entries(package, source_kind):
                if len(occurrences) >= self.max_images:
                    skipped += 1
                    continue
                try:
                    image_payload = package.read(media_path)
                except KeyError:
                    skipped += 1
                    continue
                content_type = mimetypes.guess_type(media_path)[0] or "application/octet-stream"
                occurrence = builder.build(
                    image_payload,
                    content_type=content_type,
                    source_kind=source_kind,
                    source_locator=locator,
                    metadata=metadata,
                )
                if occurrence is None:
                    skipped += 1
                else:
                    occurrences.append(occurrence)
        duplicates = sum(1 for item in occurrences if item.duplicate_of is not None)
        return EmbeddedImageExtractionResult(
            occurrences=tuple(occurrences),
            unique_image_count=builder.unique_count,
            duplicate_count=duplicates,
            skipped_count=skipped,
        )

    def _entries(self, package: zipfile.ZipFile, source_kind: str):
        if source_kind == "docx":
            return _docx_entries(package)
        if source_kind == "pptx":
            return _pptx_entries(package)
        return _xlsx_entries(package)


def _resolve(base_path: str, target: str) -> str:
    return posixpath.normpath(posixpath.join(base_path, target))


def _relationship_map(package: zipfile.ZipFile, rels_path: str, base_path: str) -> dict[str, str]:
    try:
        root = ET.fromstring(package.read(rels_path))
    except KeyError:
        return {}
    mapping = {}
    for relation in root.findall("r:Relationship", _REL_NS):
        relation_id = relation.attrib.get("Id")
        target = relation.attrib.get("Target")
        relation_type = relation.attrib.get("Type", "")
        if relation_id and target and relation_type.endswith("/image"):
            mapping[relation_id] = _resolve(base_path, target)
    return mapping


def _docx_entries(package: zipfile.ZipFile):
    rels = _relationship_map(package, "word/_rels/document.xml.rels", "word")
    return [
        (path, {"section_index": 1, "relationship_id": rel_id}, {"source": "docx_embedded_image"})
        for rel_id, path in rels.items()
    ]


def _pptx_entries(package: zipfile.ZipFile):
    entries = []
    slide_paths = sorted(
        (name for name in package.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
        key=lambda value: int(re.search(r"(\d+)", value).group(1)),
    )
    for slide_path in slide_paths:
        slide_number = int(re.search(r"slide(\d+)\.xml", slide_path).group(1))
        rels_path = f"ppt/slides/_rels/slide{slide_number}.xml.rels"
        rels = _relationship_map(package, rels_path, "ppt/slides")
        for rel_id, path in rels.items():
            entries.append(
                (path, {"slide_number": slide_number, "relationship_id": rel_id}, {"source": "pptx_embedded_image"})
            )
    return entries


def _xlsx_entries(package: zipfile.ZipFile):
    sheet_names = _xlsx_sheet_names(package)
    entries = []
    for sheet_index, sheet_name in sheet_names.items():
        sheet_rels_path = f"xl/worksheets/_rels/sheet{sheet_index}.xml.rels"
        drawing_targets = _all_relationship_targets(package, sheet_rels_path, "xl/worksheets", "/drawing")
        for drawing_path in drawing_targets:
            drawing_name = PurePosixPath(drawing_path).name
            drawing_rels = f"xl/drawings/_rels/{drawing_name}.rels"
            rels = _relationship_map(package, drawing_rels, "xl/drawings")
            for rel_id, path in rels.items():
                entries.append(
                    (path, {"sheet_name": sheet_name, "relationship_id": rel_id}, {"source": "xlsx_embedded_image"})
                )
    return entries


def _all_relationship_targets(package, rels_path, base_path, type_suffix):
    try:
        root = ET.fromstring(package.read(rels_path))
    except KeyError:
        return []
    targets = []
    for relation in root.findall("r:Relationship", _REL_NS):
        target = relation.attrib.get("Target")
        if target and relation.attrib.get("Type", "").endswith(type_suffix):
            targets.append(_resolve(base_path, target))
    return targets


def _xlsx_sheet_names(package: zipfile.ZipFile) -> dict[int, str]:
    try:
        root = ET.fromstring(package.read("xl/workbook.xml"))
    except KeyError:
        return {}
    namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    result = {}
    for position, sheet in enumerate(root.findall("m:sheets/m:sheet", namespace), start=1):
        result[position] = sheet.attrib.get("name", f"Sheet{position}")
    return result
