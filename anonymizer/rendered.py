"""Local rendering/OCR fallback. Only visible pixels and recognized text leave this adapter."""

import csv
import os
import re
import shutil
import subprocess
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from io import BytesIO, StringIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import pymupdf as fitz
from lxml import etree
from PIL import Image, ImageDraw

from .errors import UnsupportedDocument

DPI = 180
MAX_PIXELS = 120_000_000


@dataclass
class Line:
    text: str
    box: tuple
    size: float
    color: tuple = (0, 0, 0)
    native: bool = False


@dataclass
class Page:
    width: float
    height: float
    png: bytes
    lines: list[Line]


def ocr_lines(png, width, height):
    executable = shutil.which("tesseract")
    if not executable:
        raise UnsupportedDocument(
            "OCR requires Tesseract with English and French language data. See README installation."
        )
    try:
        result = subprocess.run(
            [executable, "stdin", "stdout", "-l", "eng+fra", "--dpi", str(DPI), "tsv"],
            input=png,
            capture_output=True,
            timeout=90,
            env={**os.environ, "OMP_THREAD_LIMIT": "1"},
        )
    except (OSError, subprocess.TimeoutExpired):
        raise UnsupportedDocument(
            "Local OCR failed or exceeded its 90-second page limit."
        ) from None
    if result.returncode:
        raise UnsupportedDocument(
            "Local OCR failed. Check Tesseract and its eng/fra language data installation."
        )
    with Image.open(BytesIO(png)) as image:
        sx, sy = width / image.width, height / image.height
    groups = defaultdict(list)
    for word in csv.DictReader(
        StringIO(result.stdout.decode("utf-8")), delimiter="\t", quoting=csv.QUOTE_NONE
    ):
        text = word.get("text", "").strip()
        if word["level"] != "5" or not text:
            continue
        x, y, w, h = (int(word[k]) for k in ("left", "top", "width", "height"))
        groups[(word["block_num"], word["par_num"], word["line_num"])].append(
            (text, fitz.Rect(x * sx, y * sy, (x + w) * sx, (y + h) * sy))
        )
    return list(groups.values())


def _column_groups(items):
    """Group nearby text boxes without joining distant table columns."""
    segment = []
    for item, box in items:
        if segment:
            previous = segment[-1][1]
            if box.x0 - previous.x1 > max(12, 2 * min(previous.height, box.height)):
                yield segment
                segment = []
        segment.append((item, box))
    if segment:
        yield segment


def _native_lines(page):
    # Rotated pages/text and invisible OCR layers are read from rendered pixels instead.
    if page.rotation:
        return []
    traces = page.get_texttrace()
    paint = page.get_bboxlog()
    excluded = [
        fitz.Rect(t["bbox"])
        for t in traces
        if t["type"] not in (0, 1) or t["opacity"] < 0.99 or t["dir"] != (1, 0)
    ]
    # Text painted over by a later image, filled shape or annotation must come
    # from OCR of the final appearance, not from the obscured source string.
    for trace in traces:
        rect = fitz.Rect(trace["bbox"])
        if any(
            kind in ("fill-path", "fill-image", "fill-shade") and rect.intersects(fitz.Rect(box))
            for kind, box in paint[trace["seqno"] + 1 :]
        ):
            excluded.append(rect)
    excluded.extend(fitz.Rect(a.rect) for a in page.annots() or [])
    lines = []
    for block in page.get_text("dict")["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            box = fitz.Rect(line["bbox"])
            if line["dir"] != (1, 0) or not page.rect.contains(box):
                continue
            if any(box.intersects(rect) for rect in excluded):
                continue
            for group in _column_groups(
                [(span, fitz.Rect(span["bbox"])) for span in line["spans"]]
            ):
                box = fitz.Rect(group[0][1])
                for _, span_box in group[1:]:
                    box |= span_box
                text = "".join(span["text"] for span, _ in group)
                if not text.strip() or "\ufffd" in text:
                    continue
                first = group[0][0]
                color = fitz.sRGB_to_pdf(first["color"])
                if min(color) > 0.9:
                    color = (0, 0, 0)
                lines.append(Line(text, tuple(box), first["size"], color, native=True))
    return lines


def read_pdf(data):
    """Return pages with native visible text plus OCR of remaining rendered areas."""
    pages, pixel_count = [], 0
    try:
        with fitz.open(stream=data, filetype="pdf") as source:
            if source.needs_pass or not 0 < len(source) <= 30:
                raise UnsupportedDocument("PDF must be unencrypted and contain 1-30 pages.")
            marker = source.metadata.get("keywords", "")
            for page in source:
                width, height = page.rect.width, page.rect.height
                if max(width, height) > 1500:
                    raise UnsupportedDocument("PDF page dimensions exceed the safe preview limit.")
                pixel_count += int(width * DPI / 72) * int(height * DPI / 72)
                if pixel_count > MAX_PIXELS:
                    raise UnsupportedDocument("Document exceeds the 120-megapixel rendering limit.")
                png = page.get_pixmap(dpi=DPI, alpha=False, annots=True).tobytes("png")
                words = ocr_lines(png, width, height)
                native = _native_lines(page)
                # Only keep native lines whose region contains visible OCR evidence.
                # White/occluded/hidden source text is not copied into the export.
                visible_boxes = [box for group in words for _, box in group]
                native = [
                    line
                    for line in native
                    if any(fitz.Rect(line.box).intersects(box) for box in visible_boxes)
                ]
                for group in words:
                    remaining = [
                        (text, box)
                        for text, box in group
                        if not any(
                            fitz.Rect(line.box).contains((box.tl + box.br) / 2)
                            # OCR boxes can extend below a native glyph, placing
                            # their center beside the next line. Matching text
                            # with substantial overlap is still native content,
                            # not an extra OCR line or a neighboring column.
                            or (
                                text in line.text
                                and (fitz.Rect(line.box) & box).get_area() >= box.get_area() * 0.25
                            )
                            for line in native
                        )
                    ]
                    for segment in _column_groups(remaining):
                        box = fitz.Rect(segment[0][1])
                        for _, word_box in segment[1:]:
                            box |= word_box
                        native.append(
                            Line(
                                " ".join(t for t, _ in segment),
                                tuple(box),
                                max(5, box.height * 0.9),
                            )
                        )
                native.sort(key=lambda line: (round(line.box[1], 1), line.box[0]))
                pages.append(Page(width, height, png, native))
    except UnsupportedDocument:
        raise
    except (RuntimeError, ValueError):
        raise UnsupportedDocument("Invalid or damaged PDF file.") from None
    return pages, marker


def export_pdf(pages, transform, marker):
    """Rebuild native text and changed OCR regions, preserving other pixels."""
    font = fitz.Font("helv")
    with fitz.open() as output:
        for original in pages:
            rewritten = []
            for line in original.lines:
                updated = "".join(
                    line.text[a:b] if value is None else value
                    for a, b, value in transform(line.text)
                )
                # Unchanged OCR may describe a logo or illustration incorrectly.
                # Keep its actual pixels instead of replacing them with that guess.
                if line.native or updated != line.text:
                    rewritten.append((line, updated))
            bitmap = Image.open(BytesIO(original.png)).convert("RGB")
            draw = ImageDraw.Draw(bitmap)
            sx, sy = bitmap.width / original.width, bitmap.height / original.height
            for line, _ in rewritten:
                x0, y0, x1, y1 = line.box
                draw.rectangle(
                    ((x0 - 0.8) * sx, (y0 - 0.8) * sy, (x1 + 0.8) * sx, (y1 + 0.8) * sy),
                    fill="white",
                )
            stream = BytesIO()
            bitmap.save(stream, format="PNG")
            page = output.new_page(width=original.width, height=original.height)
            page.insert_image(page.rect, stream=stream.getvalue())
            for line, updated in rewritten:
                if not updated:
                    continue
                x0, y0, x1, y1 = line.box
                right = original.width - 3
                for other in original.lines:
                    if (
                        other is not line
                        and other.box[0] >= x1
                        and other.box[1] < y1
                        and other.box[3] > y0
                    ):
                        right = min(right, other.box[0] - 2)
                size = min(line.size, (right - x0) / max(font.text_length(updated, fontsize=1), 1))
                if size < 3:
                    raise UnsupportedDocument(
                        "A replacement cannot fit on this page. Select a shorter value or use a simpler layout."
                    )
                writer = fitz.TextWriter(page.rect)
                writer.append(
                    (x0, y0 + min(y1 - y0, size * font.ascender)), updated, font=font, fontsize=size
                )
                writer.write_text(page, color=line.color)
        output.set_metadata({"keywords": "document-anonymizer:" + marker if marker else ""})
        return output.tobytes(garbage=4, deflate=True, clean=True)


def convert_docx(data):
    """Strip active/external content, then render with an isolated LibreOffice profile."""
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if not executable:
        raise UnsupportedDocument(
            "This DOCX requires LibreOffice for layout conversion. See README installation."
        )
    clean = BytesIO()
    case_marker = ""
    try:
        with ZipFile(BytesIO(data)) as source, ZipFile(clean, "w") as target:
            infos = source.infolist()
            if len(infos) > 500 or sum(i.file_size for i in infos) > 40 * 1024 * 1024:
                raise UnsupportedDocument("DOCX exceeds the safe expanded-size limit.")
            names = [i.filename for i in infos]
            if len(names) != len(set(names)) or "word/document.xml" not in names:
                raise UnsupportedDocument("Invalid or ambiguous DOCX package.")
            for name in names:
                if re.search(r"(vbaProject|activeX/)", name, re.I):
                    raise UnsupportedDocument("Macro and ActiveX content is not supported.")
                content = source.read(name)
                if name.endswith((".xml", ".rels")):
                    if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
                        raise UnsupportedDocument("DOCX XML entities are unsupported.")
                    root = etree.fromstring(
                        content, etree.XMLParser(resolve_entities=False, no_network=True)
                    )
                    if name == "docProps/core.xml":
                        identifiers = root.xpath('//*[local-name()="identifier"]/text()')
                        if identifiers and identifiers[0].startswith("document-anonymizer:"):
                            case_marker = identifiers[0]
                    if name.endswith(".rels"):
                        for rel in list(root):
                            destination = rel.get("Target", "")
                            if (
                                rel.get("TargetMode") == "External"
                                or ":" in destination
                                or destination.startswith("/")
                            ):
                                root.remove(rel)
                    # Keep cached field results; do not execute DDE, INCLUDETEXT, INCLUDEPICTURE.
                    for node in list(
                        root.xpath(
                            '//*[local-name()="instrText" or local-name()="fldChar" or local-name()="altChunk"]'
                        )
                    ):
                        node.getparent().remove(node)
                    for node in root.xpath('//*[local-name()="fldSimple"]'):
                        for key in list(node.attrib):
                            del node.attrib[key]
                    content = etree.tostring(
                        root, xml_declaration=True, encoding="UTF-8", standalone=True
                    )
                target.writestr(name, content)
    except UnsupportedDocument:
        raise
    except (BadZipFile, ValueError, KeyError, etree.XMLSyntaxError, OSError):
        raise UnsupportedDocument("Invalid or damaged DOCX file.") from None
    with tempfile.TemporaryDirectory(prefix="anonymizer-") as directory:
        folder = Path(directory)
        profile = folder / "profile"
        (profile / "user").mkdir(parents=True)
        (profile / "user/registrymodifications.xcu").write_text(
            '<?xml version="1.0"?><oor:items xmlns:oor="http://openoffice.org/2001/registry">'
            '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
            '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>'
            "</item></oor:items>"
        )
        (folder / "input.docx").write_bytes(clean.getvalue())
        try:
            result = subprocess.run(
                [
                    executable,
                    "-env:UserInstallation=" + profile.as_uri(),
                    "--headless",
                    "--norestore",
                    "--convert-to",
                    "pdf:writer_pdf_Export",
                    "--outdir",
                    str(folder),
                    str(folder / "input.docx"),
                ],
                capture_output=True,
                timeout=90,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise UnsupportedDocument(
                "Local DOCX conversion failed or exceeded its 90-second limit."
            ) from None
        output = folder / "input.pdf"
        if result.returncode or not output.exists():
            raise UnsupportedDocument(
                "LibreOffice could not render this DOCX. It may be damaged or encrypted."
            )
        with fitz.open(output) as converted:
            converted.set_metadata({"keywords": case_marker})
            return converted.tobytes(garbage=4, deflate=True)
