# Engine selection and architecture

## Decision

Use [**PII Shield 2.2.0**](https://github.com/gregmos/PII-Shield) for detection,
replacing Presidio/spaCy. GLiNER targets addresses and organizations; pattern
rules cover EU/UK identifiers. See [validation](validation.md) for measured
coverage and remaining gaps.

The Streamlit UI, document adapters and encrypted vault are application-owned.
PII Shield's CLI exports PDF input as text and lacks scanned-PDF OCR, so it receives
our extracted text via `scan --json`; our adapters retain PDF downloads and scan
support. Mapping/reference behavior is documented in the
[runbook](../README.md#configuration-and-mappings).

## Components, models and tools

All processing runs locally; no LLM or cloud AI API is used.
[requirements.txt](../requirements.txt) pins Python dependencies;
[package-lock.json](../package-lock.json) pins PII Shield and its Node dependencies.
See the [runbook](../README.md#install-and-launch) for system dependencies.

| Component | Model/tool | Purpose |
| --- | --- | --- |
| Sensitive-data detection | PII Shield 2.2.0 | Combines GLiNER, structured identifier rules and entity boundary/overlap handling |
| Language model | [`knowledgator/gliner-pii-base-v1.0`](https://huggingface.co/knowledgator/gliner-pii-base-v1.0), ONNX Runtime Node 1.22.0 | Names, organizations and addresses using one shared model |
| Custom detection | Python regular expressions | Supplements bilingual field/contact rules and common English/French postal syntax |
| OCR | Tesseract, English and French | Reads text from scans and rendered pages |
| PDF processing | PyMuPDF | Extracts text, renders pages and writes anonymized PDFs |
| Word processing | python-docx and LibreOffice | Edits simple DOCX content; converts complex documents to PDF |
| Reversible replacements | Custom Python and Fernet encryption | Assigns placeholders and encrypts persistent restoration mappings |
| Interface | Streamlit | Upload, review, manual corrections, previews and downloads |

After [setup](../README.md#install-and-launch), scans use private temporary
directories linked to installed models/dependencies. A Node preload guard blocks
network access and child processes, preventing scan-time npm bootstrap. Streamlit
telemetry is disabled.

The CLI can return success after NER failure. The adapter requires initialization
and every inference chunk to complete; this diagnostic-format check must be
retested on upgrades. Text/diagnostics are deleted after scanning. UTF-16 offsets
are converted to Python character offsets and validated against source text,
allowing whitespace normalization. Multiline spans become line/paragraph replacements.

The model card lists English. French/mixed-language coverage is checked only on
the small local corpus and supplemental rules, not a validated French benchmark.

## Data flow and modules

`app.py` → `documents.load_document` → `Detector.detect` → user review →
`service.anonymize` → `Vault.assign` → fresh document export.

Restoration validates the case marker and all placeholders against the selected
vault before replacing values. Missing mappings prevent partial restoration.

| Module | Responsibility |
| --- | --- |
| `anonymizer/documents.py` | Input validation, reading order, simple PDF/DOCX reconstruction and PDF previews |
| `anonymizer/rendered.py` | Complex DOCX conversion, PDF rasterization, OCR, text-pixel erasure and PDF export |
| `anonymizer/detection.py` | Type/offset adaptation, domain rules, overlap resolution, repeated values and manual selections |
| `anonymizer/pii_shield.py` | Version/runtime checks, private CLI scans, timeouts and complete-inference validation |
| `scripts/setup_pii_shield.py` | Model/dependency setup and offline inference smoke test |
| `scripts/pii_shield_offline.mjs` | Blocks scan-time network and child-process bootstrap |
| `anonymizer/vault.py` | Fernet-encrypted JSON per case, keys, file locking and atomic writes |
| `anonymizer/service.py` | Anonymization, export validation and restoration |
| `anonymizer/dataset.py` | Four fictional documents and exact-span annotations |
| `app.py` | Streamlit workflow and session state |

## Export and storage design

Exports rebuild containers to avoid copying arbitrary source objects. Simple PDFs
retain text and supported rules; simple DOCX files copy paragraphs, runs, tables,
built-in styles and headers/footers through a property allowlist. Source metadata,
thumbnails and custom XML are removed.

Complex DOCX packages are size checked and stripped of external relationships
and executable field instructions. LibreOffice runs with an isolated profile,
macros disabled and a private temporary directory. Cached field results remain.

For rendered inputs, PyMuPDF rasterizes pages at 180 DPI. Tesseract supplies text
and bounding boxes; visible native horizontal text is reused where OCR confirms
its presence. Rotated/image text comes from OCR; large gaps split table columns
into separate regions. Native text and edited OCR regions are erased and redrawn
in a fresh PDF. Unchanged OCR regions retain their pixels, so a misread logo is
not replaced with text. Exports are reopened to check that selected values are
absent; tests also OCR output pixels independently. See the
[runbook](../README.md#boundaries) for format, fidelity and detection limits.

Vault directories use mode `0700`, keys/files `0600` on Linux. Mappings preserve
exact originals; aliases are not merged. The random case marker is a wrong-case
guard, not a signature. Document values are not deliberately logged. See the
[runbook](../README.md#configuration-and-mappings) for assignment, retention, backup
and key handling.

## Licenses

PII Shield, Streamlit and python-docx use permissive licenses. The selected
GLiNER model is Apache-2.0; ONNX Runtime uses MIT (see their package/model metadata).
PyMuPDF is **AGPL-3.0 or commercially licensed**; distribution or hosted use must
comply with its license or use a commercial license. Tesseract uses Apache-2.0;
LibreOffice primarily uses MPL-2.0. No license has been assigned to this repository.
