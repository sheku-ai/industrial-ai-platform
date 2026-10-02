import io
import json
import zipfile
from email.message import EmailMessage

from PIL import Image, ImageDraw

from app.services.eml_embedded_image_extractor import EmlEmbeddedImageExtractor
from app.services.ooxml_embedded_image_extractor import OoxmlEmbeddedImageExtractor

REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def image_bytes():
    image = Image.new("RGB", (240, 140), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 220, 120), outline="black", width=4)
    draw.line((30, 100, 120, 40, 210, 90), fill="black", width=4)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def package(entries):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, value in entries.items():
            archive.writestr(name, value)
    return out.getvalue()


def docx(image):
    rels = (
        f'<Relationships xmlns="{REL_NS}"><Relationship Id="rId1" '
        f'Type="{OFFICE_REL}/image" Target="media/image1.png"/></Relationships>'
    )
    return package(
        {"word/document.xml": "<document/>", "word/_rels/document.xml.rels": rels, "word/media/image1.png": image}
    )


def pptx(image):
    rels = (
        f'<Relationships xmlns="{REL_NS}"><Relationship Id="rId1" '
        f'Type="{OFFICE_REL}/image" Target="../media/image1.png"/></Relationships>'
    )
    return package(
        {"ppt/slides/slide1.xml": "<slide/>", "ppt/slides/_rels/slide1.xml.rels": rels, "ppt/media/image1.png": image}
    )


def xlsx(image):
    workbook = (
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheets><sheet name="Data" sheetId="1"/></sheets></workbook>'
    )
    sheet_rels = (
        f'<Relationships xmlns="{REL_NS}"><Relationship Id="rId1" '
        f'Type="{OFFICE_REL}/drawing" Target="../drawings/drawing1.xml"/></Relationships>'
    )
    drawing_rels = (
        f'<Relationships xmlns="{REL_NS}"><Relationship Id="rId2" '
        f'Type="{OFFICE_REL}/image" Target="../media/image1.png"/></Relationships>'
    )
    return package(
        {
            "xl/workbook.xml": workbook,
            "xl/worksheets/sheet1.xml": "<worksheet/>",
            "xl/worksheets/_rels/sheet1.xml.rels": sheet_rels,
            "xl/drawings/drawing1.xml": "<drawing/>",
            "xl/drawings/_rels/drawing1.xml.rels": drawing_rels,
            "xl/media/image1.png": image,
        }
    )


def eml(image):
    message = EmailMessage()
    message["Subject"] = "Embedded image smoke"
    message["Message-ID"] = "<smoke-257@example.invalid>"
    message.set_content("Body")
    message.add_alternative('<html><body><img src="cid:inline-257"></body></html>', subtype="html")
    html_part = message.get_payload()[1]
    html_part.add_related(image, maintype="image", subtype="png", cid="inline-257")
    message.add_attachment(image, maintype="image", subtype="png", filename="diagram.png")
    return message.as_bytes()


def main():
    image = image_bytes()
    extractor = OoxmlEmbeddedImageExtractor()
    docx_result = extractor.extract(docx(image), source_kind="docx")
    pptx_result = extractor.extract(pptx(image), source_kind="pptx")
    xlsx_result = extractor.extract(xlsx(image), source_kind="xlsx")
    eml_result = EmlEmbeddedImageExtractor().extract(eml(image))

    checks = {
        "docx_extracted": len(docx_result.occurrences) == 1,
        "docx_section_provenance": docx_result.occurrences[0].source_locator.get("section_index") == 1,
        "pptx_extracted": len(pptx_result.occurrences) == 1,
        "pptx_slide_provenance": pptx_result.occurrences[0].source_locator.get("slide_number") == 1,
        "xlsx_extracted": len(xlsx_result.occurrences) == 1,
        "xlsx_sheet_provenance": xlsx_result.occurrences[0].source_locator.get("sheet_name") == "Data",
        "eml_two_occurrences": len(eml_result.occurrences) == 2,
        "eml_deduplicated": eml_result.unique_image_count == 1 and eml_result.duplicate_count == 1,
        "eml_message_provenance": all(
            item.source_locator.get("message_id") == "<smoke-257@example.invalid>" for item in eml_result.occurrences
        ),
        "hash_consistent_across_formats": len(
            {
                docx_result.occurrences[0].image.image_hash,
                pptx_result.occurrences[0].image.image_hash,
                xlsx_result.occurrences[0].image.image_hash,
                eml_result.occurrences[0].image.image_hash,
            }
        )
        == 1,
    }
    passed = all(checks.values())
    print(
        json.dumps(
            {
                "passed": passed,
                "docx_unique": docx_result.unique_image_count,
                "pptx_unique": pptx_result.unique_image_count,
                "xlsx_unique": xlsx_result.unique_image_count,
                "eml_unique": eml_result.unique_image_count,
                "eml_duplicates": eml_result.duplicate_count,
                **checks,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
