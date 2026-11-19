import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from zipfile import ZipFile

import pymupdf as fitz
import pytest
from cryptography.fernet import Fernet
from docx import Document
from docx.oxml import OxmlElement

from anonymizer.documents import _open_docx, _open_pdf, load_document
from anonymizer.errors import AnonymizerError, MappingError, UnsupportedDocument
from anonymizer.service import anonymize, restore
from anonymizer.vault import Vault


def docx_bytes(text):
    doc = Document()
    doc.add_paragraph(text)
    output = BytesIO()
    doc.save(output)
    return output.getvalue()


def assert_no_leaks(data, kind, values):
    if kind == "docx":
        with ZipFile(BytesIO(data)) as package:
            decoded = "\n".join(
                package.read(name).decode("utf-8", errors="ignore") for name in package.namelist()
            )
            assert "customXml/" not in " ".join(package.namelist())
    else:
        with fitz.open(stream=data, filetype="pdf") as pdf:
            decoded = str(pdf.metadata)
            for number in range(1, pdf.xref_length()):
                decoded += pdf.xref_object(number)
                if pdf.xref_is_stream(number):
                    stream = pdf.xref_stream(number)
                    for value in values:
                        assert value.encode() not in stream
                        assert value.encode("utf-16-be") not in stream
                    decoded += stream.decode("latin-1", errors="ignore")
            assert not pdf.embfile_count()
            assert all(not page.get_images() for page in pdf)
    for value in values:
        assert value not in decoded
        assert value not in load_document(data, "output." + kind).text


@pytest.mark.parametrize("index", range(4))
def test_roundtrip_restart_and_leaks(samples, detector, tmp_path, index):
    directory, manifest = samples
    item = manifest[index]
    path = directory / item["filename"]
    source = load_document(path.read_bytes(), path.name)
    entities = detector.detect(source.text)
    expected = {(e["start"], e["end"], e["kind"]) for e in item["entities"]}
    actual = {(e.start, e.end, e.kind) for e in entities}
    # Require every annotated value; additional model predictions are scored
    # separately by scripts.benchmark rather than prohibited by a round-trip test.
    assert expected <= actual
    vault_dir = tmp_path / "vault"
    result = anonymize(source, entities, Vault(vault_dir), "case-1")
    assert_no_leaks(result.data, result.kind, [e["value"] for e in item["entities"]])
    exported = tmp_path / ("anonymized." + result.kind)
    exported.write_bytes(result.data)
    # A completely new Python process must restore without in-memory state or the source.
    restored = tmp_path / ("restored." + result.kind)
    script = """from pathlib import Path
import sys
from anonymizer.documents import load_document
from anonymizer.service import restore
from anonymizer.vault import Vault
p = Path(sys.argv[1])
r = restore(load_document(p.read_bytes(), p.name), Vault(sys.argv[2]), 'case-1')
Path(sys.argv[3]).write_bytes(r.data)
"""
    subprocess.run(
        [sys.executable, "-c", script, str(exported), str(vault_dir), str(restored)], check=True
    )
    recovered = load_document(restored.read_bytes(), restored.name)
    assert recovered.text == source.text
    # Entire case payload is encrypted, with restrictive Unix permissions.
    for file in vault_dir.glob("*.vault"):
        assert b"Camille" not in file.read_bytes()
        assert b"Daniel" not in file.read_bytes()
        assert file.stat().st_mode & 0o777 == 0o600
    assert (vault_dir / "key.fernet").stat().st_mode & 0o777 == 0o600


def test_shared_identity_and_case_isolation(samples, detector, tmp_path):
    directory, manifest = samples
    vault = Vault(tmp_path)
    outputs = []
    for item in (manifest[0], manifest[2], manifest[3]):
        path = directory / item["filename"]
        doc = load_document(path.read_bytes(), path.name)
        outputs.append(anonymize(doc, detector.detect(doc.text), vault, "shared"))
    data = vault.get("shared")
    token = next(t for t, value in data["mapping"].items() if value == "Camille Moreau")
    assert all(token in result.text for result in outputs)
    vault.assign("different", [("Another Name", "PERSON")])
    with pytest.raises(MappingError, match="another case"):
        restore(load_document(outputs[0].data, "file.pdf"), vault, "different")


def test_manual_review_and_split_runs(tmp_path):
    doc = Document()
    p = doc.add_paragraph()
    p.add_run("Private ")
    p.add_run("Person").bold = True
    p.add_run(" / Private Person / public")
    output = BytesIO()
    doc.save(output)
    source = load_document(output.getvalue(), "source.docx")
    result = anonymize(source, [], Vault(tmp_path), "manual", [("Private Person", "PERSON")])
    assert result.text.count("[PERSON_001]") == 2
    assert "public" in result.text
    restored = restore(load_document(result.data, "source.docx"), Vault(tmp_path), "manual")
    assert restored.text == source.text
    with pytest.raises(AnonymizerError, match="not found"):
        anonymize(source, [], Vault(tmp_path), "manual", [("absent", "OTHER")])
    with pytest.raises(AnonymizerError, match="at least one"):
        anonymize(source, [], Vault(tmp_path), "manual")


@pytest.mark.parametrize(
    "token",
    ["[PERSON_999]", "[PERSON_01]", "[PERSON_001", "[UNKNOWN_001]", "[PERSON-001]", "[PERSON 001]"],
)
def test_missing_or_malformed_mappings(tmp_path, token):
    vault = Vault(tmp_path)
    vault.assign("case", [("Alice Example", "PERSON")])
    doc = load_document(docx_bytes(token), "file.docx")
    with pytest.raises(MappingError, match="Missing or malformed"):
        restore(doc, vault, "case")


def test_rearranged_authored_document(tmp_path):
    vault = Vault(tmp_path)
    vault.assign("case", [("Alice Example", "PERSON"), ("alice@example.org", "EMAIL_ADDRESS")])
    doc = load_document(
        docx_bytes("Contact [EMAIL_ADDRESS_001]. Hello [PERSON_001]."), "response.docx"
    )
    result = restore(doc, vault, "case")
    assert result.text.startswith("Contact alice@example.org. Hello Alice Example.")


def test_wrong_key_missing_key_and_corrupt_vault(tmp_path, monkeypatch):
    vault = Vault(tmp_path)
    vault.assign("case", [("Alice", "PERSON")])
    monkeypatch.setenv("ANONYMIZER_KEY", Fernet.generate_key().decode())
    with pytest.raises(MappingError, match="Cannot open"):
        Vault(tmp_path).get("case")
    monkeypatch.delenv("ANONYMIZER_KEY")
    key = (tmp_path / "key.fernet").read_bytes()
    (tmp_path / "key.fernet").unlink()
    with pytest.raises(MappingError, match="missing"):
        Vault(tmp_path)
    (tmp_path / "key.fernet").write_bytes(key)
    next(tmp_path.glob("*.vault")).write_bytes(b"corrupted")
    with pytest.raises(MappingError, match="Cannot open"):
        Vault(tmp_path).get("case")


def test_atomic_concurrent_mapping_assignment(tmp_path):
    def assign(index):
        return Vault(tmp_path).assign("shared", [(f"Person {index}", "PERSON")])

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(assign, range(12)))
    mapping = Vault(tmp_path).get("shared")["mapping"]
    assert len(mapping) == 12
    assert len(set(mapping.values())) == 12


def test_offline_processing(samples, detector, tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network access attempted during processing")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    # Exercise a cold PII Shield instance; its Node subprocess also blocks network access.
    from anonymizer.detection import Detector

    local = Detector()
    directory, manifest = samples
    for item in manifest:
        path = directory / item["filename"]
        source = load_document(path.read_bytes(), path.name)
        result = anonymize(source, local.detect(source.text), Vault(tmp_path), "offline")
        restore(load_document(result.data, path.name), Vault(tmp_path), "offline")


@pytest.mark.parametrize(
    "filename,data",
    [
        ("bad.txt", b"hello"),
        ("bad.pdf", b"not a pdf"),
        ("bad.docx", b"not a zip"),
        ("empty.pdf", b""),
    ],
)
def test_invalid_inputs(filename, data):
    with pytest.raises(UnsupportedDocument):
        load_document(data, filename)


@pytest.mark.parametrize(
    "tag", ["drawing", "fldChar", "ins", "del", "vanish", "object", "hyperlink"]
)
def test_complex_docx_requires_fallback(tag):
    doc = Document()
    run = doc.add_paragraph("Test").runs[0]
    run._r.append(OxmlElement("w:" + tag))
    output = BytesIO()
    doc.save(output)
    with pytest.raises(UnsupportedDocument):
        _open_docx(output.getvalue())


def test_complex_pdfs_require_fallback():
    for variant in ("image", "hidden", "attachment", "annotation", "blank", "rotated"):
        pdf = fitz.open()
        page = pdf.new_page()
        if variant != "blank":
            page.insert_text((50, 50), "Test document", render_mode=3 if variant == "hidden" else 0)
        if variant == "image":
            pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10), False)
            page.insert_image(fitz.Rect(10, 100, 20, 110), pixmap=pixmap)
        if variant == "attachment":
            pdf.embfile_add("secret.txt", b"secret")
        if variant == "annotation":
            page.add_text_annot((100, 100), "secret")
        if variant == "rotated":
            page.set_rotation(90)
        with pytest.raises(UnsupportedDocument):
            _open_pdf(pdf.tobytes())
        pdf.close()


@pytest.mark.parametrize(
    "features",
    [
        ("embedded images (including logos or scans)",),
        ("page rotation (90 degrees)",),
        ("annotations",),
        ("form fields",),
        ("clickable links",),
        ("embedded images (including logos or scans)", "annotations", "clickable links"),
    ],
)
def test_pdf_rejection_identifies_page_and_only_detected_features(features):
    labels = (
        "embedded images (including logos or scans)",
        "page rotation (90 degrees)",
        "annotations",
        "form fields",
        "clickable links",
    )
    with fitz.open() as pdf:
        pdf.new_page().insert_text((50, 50), "Supported first page")
        page = pdf.new_page()
        page.insert_text((50, 50), "Second page")
        if labels[0] in features:
            pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10), False)
            page.insert_image(fitz.Rect(10, 100, 20, 110), pixmap=pixmap)
        if labels[1] in features:
            page.set_rotation(90)
        if labels[2] in features:
            page.add_text_annot((100, 100), "Sensitive annotation")
        if labels[3] in features:
            widget = fitz.Widget()
            widget.field_name = "Sensitive field"
            widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
            widget.field_value = "Sensitive value"
            widget.rect = fitz.Rect(100, 100, 200, 125)
            page.add_widget(widget)
        if labels[4] in features:
            page.insert_link(
                {
                    "kind": fitz.LINK_URI,
                    "from": fitz.Rect(50, 40, 150, 60),
                    "uri": "https://example.org/sensitive",
                }
            )
        with pytest.raises(UnsupportedDocument) as error:
            _open_pdf(pdf.tobytes())
    message = str(error.value)
    assert "PDF page 2" in message
    for label in labels:
        assert (label in message) == (label in features)
    assert "Sensitive" not in message
    assert "example.org" not in message
    assert "private-filename" not in message


@pytest.mark.parametrize(
    "text,name,email",
    [
        (
            "Please contact Alice Johnson at alice.johnson@example.net.",
            "Alice Johnson",
            "alice.johnson@example.net",
        ),
        (
            "Veuillez contacter Jean Dupont à jean.dupont@example.org.",
            "Jean Dupont",
            "jean.dupont@example.org",
        ),
    ],
)
def test_unlabelled_names_and_emails(detector, text, name, email):
    entities = detector.detect(text)
    found = {(text[e.start : e.end], e.kind) for e in entities}
    assert (name, "PERSON") in found
    assert (email, "EMAIL_ADDRESS") in found


def test_docx_table_header_and_style_preservation(tmp_path):
    doc = Document()
    doc.add_paragraph("Account review", "Heading 1")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Customer"
    table.cell(0, 1).text = "Alice Johnson"
    doc.sections[0].footer.paragraphs[0].text = "Alice Johnson"
    output = BytesIO()
    doc.save(output)
    source = load_document(output.getvalue(), "source.docx")
    result = anonymize(source, [], Vault(tmp_path), "case", [("Alice Johnson", "PERSON")])
    exported = Document(BytesIO(result.data))
    assert exported.paragraphs[0].style.name == "Heading 1"
    assert exported.tables[0].cell(0, 1).text == "[PERSON_001]"
    assert exported.sections[0].footer.paragraphs[0].text == "[PERSON_001]"
