"""Editable simple documents, with rendered/OCR fallback for complex inputs."""

import re
from copy import deepcopy
from dataclasses import dataclass
from io import BytesIO
from zipfile import BadZipFile, ZipFile

import pymupdf as fitz
from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from lxml import etree

from .errors import UnsupportedDocument

MAX_BYTES = 10 * 1024 * 1024
MAX_TEXT = 200_000
MARKER = "document-anonymizer:"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
# Structures outside this allowlist use the rendered fallback.
DOCX_TAGS = {
    "document",
    "body",
    "p",
    "pPr",
    "r",
    "rPr",
    "t",
    "tab",
    "br",
    "cr",
    "tbl",
    "tblPr",
    "tblGrid",
    "gridCol",
    "tr",
    "trPr",
    "tc",
    "tcPr",
    "sectPr",
    "pgSz",
    "pgMar",
    "cols",
    "docGrid",
    "headerReference",
    "footerReference",
    "titlePg",
    "type",
    "pStyle",
    "jc",
    "spacing",
    "ind",
    "keepNext",
    "keepLines",
    "pageBreakBefore",
    "widowControl",
    "contextualSpacing",
    "outlineLvl",
    "rFonts",
    "b",
    "bCs",
    "i",
    "iCs",
    "u",
    "sz",
    "szCs",
    "color",
    "highlight",
    "lang",
    "vertAlign",
    "strike",
    "dstrike",
    "caps",
    "smallCaps",
    "kern",
    "position",
    "w",
    "shd",
    "noProof",
    "snapToGrid",
    "tblStyle",
    "tblW",
    "tblLook",
    "tblBorders",
    "top",
    "left",
    "bottom",
    "right",
    "insideH",
    "insideV",
    "start",
    "end",
    "tcW",
    "vAlign",
    "tblLayout",
    "tblCellMar",
    "trHeight",
    "cantSplit",
    "tblHeader",
    "bidi",
    "textDirection",
    "suppressAutoHyphens",
    "suppressLineNumbers",
    "header",
    "footer",
    "hdr",
    "ftr",
    "tabs",
    "defaultTabStop",
    "mirrorIndents",
    "adjustRightInd",
}
SAFE_P_PROPS = {
    "jc",
    "spacing",
    "ind",
    "keepNext",
    "keepLines",
    "pageBreakBefore",
    "widowControl",
    "contextualSpacing",
    "outlineLvl",
}
SAFE_R_PROPS = {
    "b",
    "bCs",
    "i",
    "iCs",
    "u",
    "sz",
    "szCs",
    "color",
    "highlight",
    "vertAlign",
    "strike",
    "dstrike",
    "caps",
    "smallCaps",
    "kern",
    "position",
}


@dataclass
class LoadedDocument:
    data: bytes
    kind: str
    blocks: list[str]
    marker: str | None
    pages: list | None = None
    notices: tuple[str, ...] = ()

    @property
    def text(self):
        return "\n".join(self.blocks)


def _paragraphs(container):
    for item in container.iter_inner_content():
        if isinstance(item, Paragraph):
            yield item
        elif isinstance(item, Table):
            for row in item.rows:
                for cell in row.cells:
                    yield from _paragraphs(cell)


def _containers(doc):
    yield doc
    for section in doc.sections:
        yield section.header
        yield section.first_page_header
        yield section.even_page_header
        yield section.footer
        yield section.first_page_footer
        yield section.even_page_footer


def _open_docx(data):
    try:
        with ZipFile(BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > 500 or sum(i.file_size for i in infos) > 40 * 1024 * 1024:
                raise UnsupportedDocument("DOCX exceeds the safe expanded-size limit.")
            names = [i.filename for i in infos]
            if len(names) != len(set(names)):
                raise UnsupportedDocument("DOCX has ambiguous duplicate package entries.")
            if any(
                re.search(
                    r"(embeddings/|media/|vbaProject|activeX/|comments|footnotes|endnotes)", n
                )
                for n in names
            ):
                raise UnsupportedDocument(
                    "DOCX images, macros, embedded files, comments and notes are unsupported."
                )
            for name in names:
                if not name.endswith((".xml", ".rels")):
                    continue
                raw = archive.read(name)
                if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
                    raise UnsupportedDocument("DOCX XML entities are unsupported.")
                root = etree.fromstring(
                    raw, etree.XMLParser(resolve_entities=False, no_network=True)
                )
                if name.endswith(".rels") and root.xpath(
                    '//*[local-name()="Relationship"][@TargetMode="External"]'
                ):
                    raise UnsupportedDocument(
                        "DOCX external links and relationships are unsupported."
                    )
                if name.startswith("word/") and root.xpath(
                    '//*[local-name()="vanish" or local-name()="webHidden"]'
                ):
                    raise UnsupportedDocument("DOCX hidden text is unsupported.")
                if re.fullmatch(r"word/(document|header\d+|footer\d+)\.xml", name):
                    for node in root.iter():
                        tag = etree.QName(node)
                        if tag.namespace != W or tag.localname not in DOCX_TAGS:
                            raise UnsupportedDocument(
                                "DOCX contains unsupported fields, revisions, drawings or layout structures."
                            )
        doc = Document(BytesIO(data))
        if len(doc.sections) != 1:
            raise UnsupportedDocument("DOCX with multiple sections is unsupported in this POC.")
        return doc
    except UnsupportedDocument:
        raise
    except (BadZipFile, ValueError, KeyError, etree.XMLSyntaxError, OSError):
        raise UnsupportedDocument("Invalid or damaged DOCX file.") from None


def _open_pdf(data):
    doc = None
    try:
        doc = fitz.open(stream=data, filetype="pdf")
        if doc.needs_pass or not 0 < len(doc) <= 30:
            raise UnsupportedDocument("PDF must be unencrypted and contain 1-30 pages.")
        if doc.embfile_count() or doc.get_ocgs():
            raise UnsupportedDocument(
                "PDF attachments and optional-content layers are unsupported."
            )
        for page in doc:
            if page.rect.width > 1500 or page.rect.height > 1500:
                raise UnsupportedDocument("PDF page dimensions exceed the safe preview limit.")
            unsupported = []
            if page.get_image_info():
                unsupported.append("embedded images (including logos or scans)")
            if page.rotation:
                unsupported.append(f"page rotation ({page.rotation} degrees)")
            if list(page.annots() or []):
                unsupported.append("annotations")
            if list(page.widgets() or []):
                unsupported.append("form fields")
            if page.get_links():
                unsupported.append("clickable links")
            if unsupported:
                raise UnsupportedDocument(
                    f"PDF page {page.number + 1} contains unsupported features: "
                    + "; ".join(unsupported)
                    + ". Rendered-page processing is required."
                )
            if not page.get_text().strip():
                raise UnsupportedDocument("PDF has no readable text on a page. OCR is required.")
            paint = page.get_bboxlog()
            if any(kind == "fill-shade" for kind, _ in paint):
                raise UnsupportedDocument("PDF shading requires rendered-page processing.")
            for trace in page.get_texttrace():
                if any(
                    kind in ("fill-path", "fill-image", "fill-shade")
                    and fitz.Rect(trace["bbox"]).intersects(fitz.Rect(box))
                    for kind, box in paint[trace["seqno"] + 1 :]
                ):
                    raise UnsupportedDocument(
                        "PDF overlapping content requires rendered-page processing."
                    )
                if trace["type"] != 0 or trace["opacity"] < 1 or trace["dir"] != (1, 0):
                    raise UnsupportedDocument(
                        "PDF hidden, transparent, outlined or rotated text is unsupported."
                    )
                if all(c >= 0.98 for c in trace["color"]):
                    raise UnsupportedDocument("PDF white text is unsupported.")
                if not page.rect.contains(fitz.Rect(trace["bbox"])):
                    raise UnsupportedDocument("PDF contains text outside the page boundary.")
            for drawing in page.get_drawings():
                for item in drawing["items"]:
                    if item[0] not in ("l", "re"):
                        raise UnsupportedDocument(
                            "PDF vector illustrations or outlined text are unsupported."
                        )
                    if item[0] == "l" and item[1].x != item[2].x and item[1].y != item[2].y:
                        raise UnsupportedDocument(
                            "PDF supports only horizontal/vertical rules and rectangles."
                        )
        return doc
    except UnsupportedDocument:
        if doc is not None:
            doc.close()
        raise
    except (RuntimeError, ValueError):
        if doc is not None:
            doc.close()
        raise UnsupportedDocument("Invalid or damaged PDF file.") from None


def _pdf_lines(page):
    return [
        line
        for block in page.get_text("dict", sort=True)["blocks"]
        if block["type"] == 0
        for line in block["lines"]
    ]


def _load_simple_document(data, filename):
    if not data or len(data) > MAX_BYTES:
        raise UnsupportedDocument("Choose a nonempty document no larger than 10 MB.")
    extension = filename.rsplit(".", 1)[-1].lower()
    if extension == "docx":
        doc = _open_docx(data)
        blocks = [p.text for c in _containers(doc) for p in _paragraphs(c)]
        marker = doc.core_properties.identifier
    elif extension == "pdf":
        with _open_pdf(data) as doc:
            blocks = [
                "".join(s["text"] for s in line["spans"])
                for page in doc
                for line in _pdf_lines(page)
            ]
            marker = doc.metadata.get("keywords", "")
    else:
        raise UnsupportedDocument("Only text-based PDF and DOCX files are supported.")
    if len("\n".join(blocks)) > MAX_TEXT:
        raise UnsupportedDocument("Document exceeds the 200,000 character limit.")
    if not any(block.strip() for block in blocks):
        raise UnsupportedDocument("Document contains no readable text.")
    return LoadedDocument(
        data, extension, blocks, marker[len(MARKER) :] if marker.startswith(MARKER) else None
    )


def load_document(data, filename):
    if not data or len(data) > MAX_BYTES:
        raise UnsupportedDocument("Choose a nonempty document no larger than 10 MB.")
    extension = filename.rsplit(".", 1)[-1].lower()
    if extension not in ("pdf", "docx"):
        raise UnsupportedDocument("Only PDF and DOCX files are supported.")
    try:
        return _load_simple_document(data, filename)
    except UnsupportedDocument:
        # Complex structures use rendered pixels instead of copying source objects.
        from .rendered import convert_docx, read_pdf

        notices = [
            "Rendered-page mode: images, layout, forms and visible annotations are flattened. "
            "Links, attachments and hidden source content are removed. Text fonts may change.",
            "English/French OCR is used for image text. Review the extracted text and output: "
            "OCR can miss or misread names, handwriting, small text and rotated text. "
            "Photos, signatures and QR/barcodes are not anonymized automatically.",
        ]
        if extension == "docx":
            data = convert_docx(data)
            notices.insert(
                0,
                "This complex DOCX is converted locally. Downloads are PDF to preserve its page layout.",
            )
        pages, marker = read_pdf(data)
        blocks = [line.text for page in pages for line in page.lines]
        if len("\n".join(blocks)) > MAX_TEXT:
            raise UnsupportedDocument("Document exceeds the 200,000 character limit.")
        if not any(block.strip() for block in blocks):
            raise UnsupportedDocument(
                "No readable text was found, including by OCR. Use a clearer scan or text document."
            )
        return LoadedDocument(
            data,
            "pdf",
            blocks,
            marker[len(MARKER) :] if marker.startswith(MARKER) else None,
            pages=pages,
            notices=tuple(notices),
        )


def _copy_props(source, target, tag, allowed):
    props = source.find(qn("w:" + tag))
    if props is not None:
        clean = target.get_or_add_pPr() if tag == "pPr" else target.get_or_add_rPr()
        for node in props:
            if etree.QName(node).localname in allowed:
                # Standard formatting values only, no arbitrary attributes or nested XML.
                copied = deepcopy(node)
                for child in list(copied):
                    copied.remove(child)
                for key in list(copied.attrib):
                    value = copied.attrib[key]
                    if not re.fullmatch(r"[A-Za-z0-9#.-]{1,24}", value):
                        del copied.attrib[key]
                for previous in list(clean):
                    if previous.tag == copied.tag:
                        clean.remove(previous)
                clean.append(copied)


def _write_paragraph(source, target, transform):
    # Preserve built-in hierarchy without copying potentially sensitive style names.
    name = source.style.name
    if name in ("Title", "Subtitle", "Normal", "List Bullet", "List Number") or re.fullmatch(
        r"Heading [1-9]", name
    ):
        target.style = name
    _copy_props(source._p, target._p, "pPr", SAFE_P_PROPS)
    chunks = transform(source.text)
    # Replacement inherits the style of its first character. Unchanged text keeps its run style.
    positions = []
    cursor = 0
    for run in source.runs:
        positions.append((cursor, cursor + len(run.text), run))
        cursor += len(run.text)
    for start, end, replacement in chunks:
        if replacement is not None:
            original = next((r for a, b, r in positions if a <= start < b), None)
            new = target.add_run(replacement)
            if original is not None:
                _copy_props(original._r, new._r, "rPr", SAFE_R_PROPS)
        else:
            for a, b, original in positions:
                if a < end and b > start:
                    new = target.add_run(original.text[max(0, start - a) : min(b, end) - a])
                    _copy_props(original._r, new._r, "rPr", SAFE_R_PROPS)


def _copy_container(source, target, transform):
    for child in list(target._element):
        if child.tag in (qn("w:p"), qn("w:tbl")):
            target._element.remove(child)
    for item in source.iter_inner_content():
        if isinstance(item, Paragraph):
            _write_paragraph(item, target.add_paragraph(), transform)
        elif hasattr(target, "add_table"):
            try:
                table = target.add_table(rows=len(item.rows), cols=len(item.columns))
            except TypeError:
                table = target.add_table(
                    rows=len(item.rows),
                    cols=len(item.columns),
                    width=item.columns[0].width * len(item.columns),
                )
            table.style = "Table Grid"
            table.autofit = item.autofit
            for a, b in zip(item.columns, table.columns):
                b.width = a.width
            for row_a, row_b in zip(item.rows, table.rows):
                for cell_a, cell_b in zip(row_a.cells, row_b.cells):
                    cell_b.width = cell_a.width
                    cell_b.vertical_alignment = cell_a.vertical_alignment
                    _copy_container(cell_a, cell_b, transform)
                    if not cell_b.paragraphs:
                        cell_b.add_paragraph()


def _render_docx(loaded, transform, marker):
    source = _open_docx(loaded.data)
    target = Document()
    for border in list(target.styles["Title"].element.iter(qn("w:pBdr"))):
        border.getparent().remove(border)
    for style in source.styles:
        name = style.name
        if name in (
            "Title",
            "Subtitle",
            "Normal",
            "List Bullet",
            "List Number",
            "Header",
            "Footer",
        ) or re.fullmatch(r"Heading [1-9]", name):
            if name in target.styles:
                destination = target.styles[name]
                _copy_props(style.element, destination.element, "pPr", SAFE_P_PROPS)
                _copy_props(style.element, destination.element, "rPr", SAFE_R_PROPS)
                if style.font.name in (
                    "Arial",
                    "Calibri",
                    "Cambria",
                    "Times New Roman",
                    "Courier New",
                ):
                    destination.font.name = style.font.name
    for a, b in zip(source.sections, target.sections):
        for prop in (
            "page_width",
            "page_height",
            "top_margin",
            "bottom_margin",
            "left_margin",
            "right_margin",
            "header_distance",
            "footer_distance",
            "different_first_page_header_footer",
        ):
            setattr(b, prop, getattr(a, prop))
    for a, b in zip(_containers(source), _containers(target)):
        _copy_container(a, b, transform)
    props = target.core_properties
    for prop in (
        "author",
        "last_modified_by",
        "title",
        "subject",
        "keywords",
        "comments",
        "category",
    ):
        setattr(props, prop, "")
    props.identifier = MARKER + marker if marker else ""
    out = BytesIO()
    target.save(out)
    # Drop template thumbnails, custom XML and their relationships.
    clean = BytesIO()
    with ZipFile(BytesIO(out.getvalue())) as raw, ZipFile(clean, "w") as archive:
        for name in raw.namelist():
            if name.startswith(("customXml/", "docProps/thumbnail")):
                continue
            content = raw.read(name)
            if name.endswith(".rels") or name == "[Content_Types].xml":
                root = etree.fromstring(content)
                for node in list(root):
                    path = node.get("Target", "") + node.get("PartName", "")
                    if "customXml" in path or "thumbnail" in path:
                        root.remove(node)
                content = etree.tostring(
                    root, xml_declaration=True, encoding="UTF-8", standalone=True
                )
            archive.writestr(name, content)
    return clean.getvalue()


def _render_pdf(loaded, transform, marker):
    fonts = {name: fitz.Font(name) for name in ("helv", "hebo", "heit", "hebi")}
    with fitz.open() as out, _open_pdf(loaded.data) as source:
        for original in source:
            page = out.new_page(width=original.rect.width, height=original.rect.height)
            for drawing in original.get_drawings():
                shape = page.new_shape()
                for item in drawing["items"]:
                    if item[0] == "l":
                        shape.draw_line(item[1], item[2])
                    else:
                        shape.draw_rect(item[1])
                shape.finish(
                    color=drawing["color"], fill=drawing["fill"], width=drawing["width"] or 0.5
                )
                shape.commit()
            lines = _pdf_lines(original)
            for line in lines:
                text = "".join(s["text"] for s in line["spans"])
                updated = "".join(
                    text[a:b] if value is None else value for a, b, value in transform(text)
                )
                if not updated:
                    continue
                first = line["spans"][0]
                bold, italic = bool(first["flags"] & 16), bool(first["flags"] & 2)
                font = fonts[
                    "hebi" if bold and italic else "hebo" if bold else "heit" if italic else "helv"
                ]
                x, y = first["origin"]
                # Use original line width, allowing free space only up to the next column/page edge.
                right = page.rect.width - 24
                for other in lines:
                    if (
                        other["bbox"][0] > line["bbox"][2]
                        and abs(other["bbox"][1] - line["bbox"][1]) < 4
                    ):
                        right = min(right, other["bbox"][0] - 6)
                available = right - x
                size = min(first["size"], available / max(font.text_length(updated, fontsize=1), 1))
                if size < 6:
                    raise UnsupportedDocument(
                        "A PDF replacement cannot fit legibly. Use a simpler layout or shorter selection."
                    )
                writer = fitz.TextWriter(page.rect)
                writer.append((x, y), updated, font=font, fontsize=size)
                color = fitz.sRGB_to_pdf(first["color"])
                writer.write_text(page, color=color)
        out.set_metadata({"keywords": MARKER + marker if marker else ""})
        return out.tobytes(garbage=4, deflate=True, clean=True)


def export_document(loaded, transform, marker=None):
    if loaded.pages is not None:
        from .rendered import export_pdf

        return export_pdf(loaded.pages, transform, marker)
    if loaded.kind == "docx":
        return _render_docx(loaded, transform, marker)
    return _render_pdf(loaded, transform, marker)


def preview_pdf(data):
    with fitz.open(stream=data, filetype="pdf") as doc:
        return [page.get_pixmap(matrix=fitz.Matrix(1.3, 1.3)).tobytes("png") for page in doc]
