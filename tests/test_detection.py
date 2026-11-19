"""PII Shield boundary checks and unlabeled document regression coverage."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from anonymizer.detection import Detector, _shield_entities
from anonymizer.errors import AnonymizerError
from anonymizer.pii_shield import GUARD, Shield, node_command


def test_utf16_offsets_and_multiline_addresses():
    text = "😀 Client\n42 Willow Lane\nBristol BS1 4QA\n"
    start, end = text.index("42"), text.rindex("\n")
    raw = {
        "start": len(text[:start].encode("utf-16-le")) // 2,
        "end": len(text[:end].encode("utf-16-le")) // 2,
        "text": text[start:end],
        "type": "LOCATION",
        "score": 0.7,
    }
    entities = list(_shield_entities(text, [raw]))
    assert [(text[e.start : e.end], e.kind) for e in entities] == [
        ("42 Willow Lane", "ADDRESS"),
        ("Bristol BS1 4QA", "ADDRESS"),
    ]
    raw["start"] = 1  # Inside the emoji surrogate pair, not a Python character boundary.
    with pytest.raises(AnonymizerError, match="invalid entity spans"):
        list(_shield_entities(text, [raw]))


@pytest.mark.parametrize(
    "field,value", [("text", "wrong"), ("score", float("nan")), ("end", 999), ("type", "INVALID")]
)
def test_invalid_engine_spans_are_rejected(field, value):
    raw = {"start": 0, "end": 10, "text": "John Smith", "type": "PERSON", "score": 0.8}
    raw[field] = value
    with pytest.raises(AnonymizerError, match="invalid entity spans"):
        list(_shield_entities("John Smith", [raw]))


@pytest.mark.parametrize(
    "mode",
    [
        "patterns_only",
        "partial",
        "inference_error",
        "bad_json",
        "wrong_length",
        "exit_error",
        "timeout",
    ],
)
def test_failed_or_partial_scans_are_not_accepted(tmp_path, monkeypatch, mode):
    shield = Shield.__new__(Shield)
    shield.node, shield.directory = "node", tmp_path

    def scan(command, **kwargs):
        folder = Path(kwargs["env"]["PII_SHIELD_DATA_DIR"])
        assert "Confidential Name" not in " ".join(command)
        assert (folder / "document.txt").stat().st_mode & 0o777 == 0o600
        if mode == "timeout":
            raise subprocess.TimeoutExpired(command, 300)
        audit = folder / "audit"
        audit.mkdir()
        before = "[NER-Inference] BEFORE _gliner.inference()\n"
        after = "[NER-Inference] AFTER _gliner.inference()\n"
        (audit / "server.log").write_text(before + ("" if mode == "partial" else after))
        ner = "[NER] GLiNER initialized\n" if mode != "patterns_only" else ""
        (audit / "ner_init.log").write_text(
            ner + ("[NER] Inference error:" if mode == "inference_error" else "")
        )
        payload = {
            "char_count": 999 if mode == "wrong_length" else len("Confidential Name"),
            "entities": [],
        }
        scan.folder = folder
        return SimpleNamespace(
            returncode=1 if mode == "exit_error" else 0,
            stdout="bad" if mode == "bad_json" else json.dumps(payload),
        )

    monkeypatch.setattr(subprocess, "run", scan)
    with pytest.raises(AnonymizerError) as error:
        shield.detect("Confidential Name")
    assert "Confidential Name" not in str(error.value)
    if mode != "timeout":
        assert not scan.folder.exists()


def test_missing_engine_has_setup_guidance(tmp_path, monkeypatch):
    monkeypatch.setenv("ANONYMIZER_ENGINE_DIR", str(tmp_path))
    with pytest.raises(AnonymizerError, match="scripts.setup_pii_shield"):
        Shield()


def test_scan_guard_blocks_network_and_bootstrap():
    script = """
    import net from 'node:net';
    import { spawnSync } from 'node:child_process';
    let blocked = 0;
    try { net.connect(9, '127.0.0.1'); } catch { blocked++; }
    try { await fetch('https://example.org'); } catch { blocked++; }
    try { spawnSync('npm', ['--version']); } catch { blocked++; }
    process.exit(blocked === 3 ? 0 : 1);
    """
    subprocess.run(
        [node_command(), "--import", str(GUARD), "--input-type=module", "-e", script],
        check=True,
        timeout=10,
    )


def test_unlabeled_invoice_entities(detector):
    text = (
        "Invoice\nAcme Ireland Limited\nBill to\nExample Consulting SAS\n"
        "42 Willow Lane\nBristol BS1 4QA\nUnited Kingdom\n"
        "Contact John Smith at john.smith@example.net\nEU VAT FR40303265045\n"
    )
    entities = detector.detect(text)
    values = [(text[e.start : e.end], e.kind) for e in entities]
    assert any("Acme" in value and kind == "ORGANIZATION" for value, kind in values)
    assert any("Willow Lane" in value and kind == "ADDRESS" for value, kind in values)
    assert ("john.smith@example.net", "EMAIL_ADDRESS") in values
    assert any(kind == "EU_VAT" for _, kind in values)


def test_real_unicode_offsets(detector):
    text = "😀 Contact Alice Johnson at alice.johnson@example.net."
    values = {(text[e.start : e.end], e.kind) for e in detector.detect(text)}
    assert ("Alice Johnson", "PERSON") in values
    assert ("alice.johnson@example.net", "EMAIL_ADDRESS") in values


@pytest.fixture
def postal_detector():
    # Simulate the real failure: PII Shield returns no span for a city line.
    detector = Detector.__new__(Detector)
    detector.shield = SimpleNamespace(detect=lambda text: [])
    return detector


@pytest.mark.parametrize(
    "text,expected",
    [
        ("42 Willow Lane\nDublin\nIreland", ["Dublin", "Ireland"]),
        ("18 rue des Lilas\nLyon\nFrance", ["Lyon", "France"]),
        (
            "Address: 42 Willow Lane\nNewcastle upon Tyne\nUnited Kingdom",
            ["Newcastle upon Tyne", "United Kingdom"],
        ),
        # Reading order interleaves two invoice columns at the same vertical position.
        (
            "42 Willow Lane\n18 rue des Lilas\nDublin\n75001 Paris\nCo. Dublin\nFrance\nD02 XY76",
            ["Dublin", "Co. Dublin", "France"],
        ),
    ],
)
def test_address_block_includes_standalone_places(postal_detector, text, expected):
    values = {(text[e.start : e.end], e.kind) for e in postal_detector.detect(text)}
    assert all((value, "ADDRESS") in values for value in expected)


@pytest.mark.parametrize(
    "following",
    [
        "\nDublin",
        "Invoice\nDublin",
        "Payment Terms\nDublin",
        "Total\nDublin",
        "Thank you for your business\nDublin",
        "Email: public@example.net\nDublin",
    ],
)
def test_address_block_stops_at_boundaries(postal_detector, following):
    text = "42 Willow Lane\n" + following
    values = {text[e.start : e.end] for e in postal_detector.detect(text) if e.kind == "ADDRESS"}
    assert values == {"42 Willow Lane"}


def test_bare_city_without_address_context_is_not_added(postal_detector):
    assert postal_detector.detect("Dublin\nIreland") == []


def test_interleaved_pdf_city_roundtrip(postal_detector, tmp_path):
    import pymupdf

    from anonymizer.documents import load_document
    from anonymizer.service import anonymize, restore
    from anonymizer.vault import Vault

    with pymupdf.open() as pdf:
        page = pdf.new_page()
        for x, y, text in [
            (50, 70, "Invoice"),
            (50, 110, "42 Willow Lane"),
            (300, 110, "18 rue des Lilas"),
            (50, 128, "Dublin"),
            (300, 128, "75001 Paris"),
            (50, 146, "Ireland"),
            (300, 146, "France"),
            (50, 190, "Total"),
        ]:
            page.insert_text((x, y), text)
        source = load_document(pdf.tobytes(), "invoice.pdf")
    entities = postal_detector.detect(source.text)
    vault = Vault(tmp_path / "vault")
    result = anonymize(source, entities, vault, "invoice")
    assert "Dublin" not in result.text
    assert "Ireland" not in result.text
    assert "Total" in result.text
    recovered = restore(load_document(result.data, "anonymous.pdf"), vault, "invoice")
    assert recovered.text == source.text
