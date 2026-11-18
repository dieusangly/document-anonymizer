"""Complex inputs must be usable and selected text must leave both pixels and objects."""

from io import BytesIO
from http.server import BaseHTTPRequestHandler, HTTPServer
import subprocess
import sys
from threading import Thread
from zipfile import ZipFile

import pymupdf as fitz
import pytest
from docx import Document
from docx.enum.section import WD_SECTION_START
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches

from anonymizer.documents import load_document
from anonymizer.errors import MappingError, UnsupportedDocument
from anonymizer.rendered import ocr_lines
from anonymizer.service import anonymize, restore
from anonymizer.vault import Vault


def text_image():
    with fitz.open() as pdf:
        page = pdf.new_page(width=400, height=100)
        page.insert_text((15, 45), "Alice Johnson", fontsize=24)
        return page.get_pixmap(dpi=180).tobytes("png")


def complex_pdf(feature):
    with fitz.open() as pdf:
        page = pdf.new_page(width=612, height=792)
        if feature != "scan":
            page.insert_text((50, 60), "Client: Alice Johnson", fontsize=16)
        if feature in ("image", "scan", "combined"):
            page.insert_image(fitz.Rect(50, 120, 450, 220), stream=text_image())
        if feature in ("link", "combined"):
            page.insert_link(
                {
                    "kind": fitz.LINK_URI,
                    "from": fitz.Rect(50, 40, 220, 65),
                    "uri": "https://example.org/Alice-Johnson",
                }
            )
        if feature == "form":
            widget = fitz.Widget()
            widget.field_name = "Private owner"
            widget.field_value = "Alice Johnson"
            widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
            widget.text_fontsize = 16
            widget.rect = fitz.Rect(50, 100, 250, 130)
            page.add_widget(widget)
        if feature == "annotation":
            page.add_freetext_annot(fitz.Rect(50, 100, 250, 140), "Alice Johnson", fontsize=16)
        if feature == "rotation":
            page.set_rotation(90)
        if feature in ("hidden", "combined"):
            page.insert_text((50, 400), "Invisible Original", render_mode=3)
            pdf.embfile_add("private.txt", b"Invisible Original")
            pdf.set_metadata({"author": "Invisible Original"})
        if feature == "covered":
            page.insert_text((50, 400), "Invisible Original", fontsize=16)
            page.draw_rect(fitz.Rect(40, 370, 300, 420), fill=(1, 1, 1), color=None)
            page.insert_text((50, 400), "Alice Johnson", fontsize=16)
        if feature == "vectors":
            page.draw_circle((400, 100), 30, color=(0, 0, 1))
        return pdf.tobytes()


def assert_clean_rendered(result):
    with fitz.open(stream=result.data, filetype="pdf") as pdf:
        assert not pdf.embfile_count()
        assert "Invisible Original" not in str(pdf.metadata)
        for page in pdf:
            assert not page.get_links()
            assert not list(page.annots() or [])
            assert not list(page.widgets() or [])
            # OCR a fresh rendering, independent of the selectable text layer.
            png = page.get_pixmap(dpi=180).tobytes("png")
            visible = " ".join(
                t for words in ocr_lines(png, page.rect.width, page.rect.height) for t, _ in words
            )
            assert "Alice Johnson" not in visible
            assert "Invisible Original" not in visible
            assert "Alice Johnson" not in page.get_text()
            # The actual embedded image must also be scrubbed, not just covered by text.
            for info in page.get_images():
                image = pdf.extract_image(info[0])
                pixels = " ".join(
                    t
                    for words in ocr_lines(image["image"], page.rect.width, page.rect.height)
                    for t, _ in words
                )
                assert "Alice Johnson" not in pixels
        for xref in range(1, pdf.xref_length()):
            decoded = (
                pdf.xref_stream(xref)
                if pdf.xref_is_stream(xref)
                else pdf.xref_object(xref).encode()
            )
            assert b"Invisible Original" not in decoded
            assert b"Alice Johnson" not in decoded
            assert b"example.org" not in decoded


@pytest.mark.parametrize(
    "feature",
    [
        "image",
        "scan",
        "link",
        "form",
        "annotation",
        "rotation",
        "hidden",
        "vectors",
        "combined",
        "covered",
    ],
)
def test_complex_pdf_roundtrip_and_pixel_privacy(tmp_path, feature):
    source = load_document(complex_pdf(feature), "source.pdf")
    assert source.pages is not None
    assert "Alice Johnson" in source.text
    assert "Invisible Original" not in source.text
    vault = Vault(tmp_path)
    result = anonymize(source, [], vault, "case", [("Alice Johnson", "PERSON")])
    assert "[PERSON_001]" in result.text
    assert_clean_rendered(result)
    recovered = restore(load_document(result.data, "output.pdf"), Vault(tmp_path), "case")
    assert recovered.text == source.text


def complex_docx():
    doc = Document()
    doc.add_paragraph("Client: Alice Johnson")
    doc.add_picture(BytesIO(text_image()), width=Inches(4))
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).merge(table.cell(0, 1)).text = "Merged heading"
    table.cell(1, 0).text = "Alice Johnson"
    doc.sections[0].header.paragraphs[0].text = "Account summary"
    doc.add_section(WD_SECTION_START.NEW_PAGE)
    paragraph = doc.add_paragraph()
    link = OxmlElement("w:hyperlink")
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = "Contact Alice Johnson"
    run.append(text)
    link.append(run)
    relationship = doc.part.relate_to(
        "https://example.org/private",
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    link.set(qn("r:id"), relationship)
    paragraph._p.append(link)
    output = BytesIO()
    doc.save(output)
    return output.getvalue()


def test_complex_docx_converts_and_roundtrips(tmp_path):
    source = load_document(complex_docx(), "source.docx")
    assert source.kind == "pdf"
    assert "Downloads are PDF" in source.notices[0]
    assert "Merged heading" in source.text
    assert "Contact Alice Johnson" in source.text
    assert len(source.pages) == 2
    vault = Vault(tmp_path)
    result = anonymize(source, [], vault, "case", [("Alice Johnson", "PERSON")])
    assert result.count >= 4
    assert_clean_rendered(result)
    recovered = restore(load_document(result.data, "output.pdf"), Vault(tmp_path), "case")
    assert recovered.text == source.text


def test_missing_system_tools_are_actionable(monkeypatch):
    monkeypatch.setattr("anonymizer.rendered.shutil.which", lambda name: None)
    with pytest.raises(UnsupportedDocument, match="Tesseract"):
        load_document(complex_pdf("image"), "source.pdf")
    with pytest.raises(UnsupportedDocument, match="LibreOffice"):
        load_document(complex_docx(), "source.docx")


def test_encrypted_blank_and_active_inputs_still_fail():
    with fitz.open() as pdf:
        pdf.new_page()
        with pytest.raises(UnsupportedDocument, match="No readable text"):
            load_document(pdf.tobytes(), "blank.pdf")
        encrypted = pdf.tobytes(
            encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="password"
        )
        with pytest.raises(UnsupportedDocument, match="unencrypted"):
            load_document(encrypted, "encrypted.pdf")
    package = BytesIO()
    with ZipFile(BytesIO(complex_docx())) as source, ZipFile(package, "w") as target:
        for name in source.namelist():
            target.writestr(name, source.read(name))
        target.writestr("word/vbaProject.bin", b"macro")
    with pytest.raises(UnsupportedDocument, match="Macro"):
        load_document(package.getvalue(), "active.docx")


def test_rendered_restore_in_a_new_process(tmp_path):
    source = load_document(complex_pdf("scan"), "scan.pdf")
    result = anonymize(source, [], Vault(tmp_path / "vault"), "case", [("Alice Johnson", "PERSON")])
    exported = tmp_path / "anonymized.pdf"
    restored = tmp_path / "restored.pdf"
    exported.write_bytes(result.data)
    subprocess.run(
        [
            sys.executable,
            "-c",
            """from pathlib import Path
import sys
from anonymizer.documents import load_document
from anonymizer.service import restore
from anonymizer.vault import Vault
p = Path(sys.argv[1])
result = restore(load_document(p.read_bytes(), p.name), Vault(sys.argv[2]), 'case')
Path(sys.argv[3]).write_bytes(result.data)
""",
            str(exported),
            str(tmp_path / "vault"),
            str(restored),
        ],
        check=True,
    )
    assert load_document(restored.read_bytes(), restored.name).text == source.text


def test_conversion_does_not_fetch_linked_images_or_execute_fields(tmp_path):
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(text_image())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        secret = tmp_path / "private.txt"
        secret.write_text("UNREQUESTED PRIVATE CONTENT")
        doc = Document()
        doc.add_paragraph("Client: Alice Johnson")
        picture = doc.add_picture(BytesIO(text_image()), width=Inches(4))
        relation_id = picture._inline.graphic.graphicData.pic.blipFill.blip.embed
        relation = doc.part.rels[relation_id]
        relation._is_external = True
        relation._target = f"http://127.0.0.1:{server.server_port}/private.png"
        field = OxmlElement("w:fldSimple")
        field.set(qn("w:instr"), f'INCLUDETEXT "{secret}"')
        run = OxmlElement("w:r")
        text = OxmlElement("w:t")
        text.text = "Cached field value"
        run.append(text)
        field.append(run)
        doc.add_paragraph()._p.append(field)
        data = BytesIO()
        doc.save(data)
        source = load_document(data.getvalue(), "linked.docx")
        assert source.kind == "pdf"
        assert "Alice Johnson" in source.text
        assert "UNREQUESTED PRIVATE CONTENT" not in source.text
        assert "Cached field value" in source.text
        assert hits == []
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_complex_docx_keeps_case_guard(tmp_path):
    vault = Vault(tmp_path)
    stored = vault.assign("original", [("Alice Johnson", "PERSON")])
    vault.assign("wrong", [("Bob Example", "PERSON")])
    doc = Document(BytesIO(complex_docx()))
    doc.core_properties.identifier = "document-anonymizer:" + stored["id"]
    doc.add_paragraph("[PERSON_001]")
    data = BytesIO()
    doc.save(data)
    loaded = load_document(data.getvalue(), "edited.docx")
    assert loaded.marker == stored["id"]
    with pytest.raises(MappingError, match="another case"):
        restore(loaded, vault, "wrong")
