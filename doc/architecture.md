# Engine selection and architecture

## Decision

Use **Microsoft Presidio Analyzer** with local spaCy models and document adapters.
It fits the Python/Streamlit application and supports custom recognizers without
an additional model runtime. This was a lightweight integration assessment based
on the [tool survey](state_of_the_art.md), not a comparative accuracy benchmark.

| Candidate | Integration assessment |
| --- | --- |
| [PII Shield](https://github.com/gregmos/PII-Shield) | Persistent mappings and native document workflows, but requires Node.js and a separate model/runtime |
| [DocCloak](https://github.com/WLojek/DocCloak) | Multilingual browser tooling; integrating WASM and persistent encrypted mappings would expand this POC |
| [Lethe](https://github.com/moonlight-lupin/lethe) | Python and encrypted mappings fit, but PDF-to-DOCX conversion conflicts with PDF output/restoration |
| [Presidio](https://presidio.dataprivacystack.org/) | Selected for extensible Python recognizers and local spaCy integration; document adapters and persistent mappings are implemented here |

## Components, models and tools

All processing runs locally; no LLM or cloud AI API is used.
[requirements.txt](../requirements.txt) pins Python dependencies and model versions.
See the [runbook](../README.md#install-and-launch) for system dependencies.

| Component | Model/tool | Purpose |
| --- | --- | --- |
| Sensitive-data detection | Microsoft Presidio Analyzer | Combines entity recognition with pattern-based email, phone, bank-detail and other detectors |
| English language model | spaCy `en_core_web_sm` 3.8.0 | Recognizes entities such as person names |
| French language model | spaCy `fr_core_news_sm` 3.8.0 | French entity recognition |
| Custom detection | Python regular expressions | Matches bilingual labeled fields such as `Address:`, `Date of birth:` and `Customer ID:` |
| OCR | Tesseract, English and French | Reads text from scans and rendered pages |
| PDF processing | PyMuPDF | Extracts text, renders pages and writes anonymized PDFs |
| Word processing | python-docx and LibreOffice | Edits simple DOCX content; converts complex documents to PDF |
| Reversible replacements | Custom Python and Fernet encryption | Assigns placeholders and encrypts persistent restoration mappings |
| Interface | Streamlit | Upload, review, manual corrections, previews and downloads |

Both spaCy models run on every input. Missing models produce an installation
error rather than a runtime download. Email validation uses the packaged suffix
list with network updates disabled; Streamlit telemetry is disabled.
Detection configuration and known gaps are documented in the
[runbook](../README.md#configuration-and-mappings).

## Data flow and modules

`app.py` → `documents.load_document` → `Detector.detect` → user review →
`service.anonymize` → `Vault.assign` → fresh document export.

Restoration validates the case marker and all placeholders against the selected
vault before replacing values. Missing mappings prevent partial restoration.

| Module | Responsibility |
| --- | --- |
| `anonymizer/documents.py` | Input validation, reading order, simple PDF/DOCX reconstruction and PDF previews |
| `anonymizer/rendered.py` | Complex DOCX conversion, PDF rasterization, OCR, text-pixel erasure and PDF export |
| `anonymizer/detection.py` | Presidio/models, domain rules, overlap resolution, repeated values and manual selections |
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
its presence. Rotated/image text comes from OCR. Recognized text rectangles are
erased from the image before transformed text is drawn into a fresh PDF. The
service reopens exports and checks that selected values are absent; tests also
OCR output pixels independently. See the [runbook](../README.md#boundaries) for
format, fidelity and detection limits.

Mappings preserve exact spelling and spacing so restoration can recover those
values; aliases are not merged. A random case marker prevents accidental use of
the wrong vault but is not a signature. Vault directories use mode `0700`, keys
and files `0600` on Linux. A process lock and atomic writes protect concurrent
updates. Document values are not deliberately logged. Storage lifetime, backup
and key configuration are covered in the [runbook](../README.md#configuration-and-mappings).

## Licenses

Presidio, Streamlit and python-docx use permissive licenses. The selected spaCy
English model is MIT; the French model is LGPL-LR (see installed model metadata).
PyMuPDF is **AGPL-3.0 or commercially licensed**; distribution or hosted use must
comply with its license or use a commercial license. Tesseract uses Apache-2.0;
LibreOffice primarily uses MPL-2.0. No license has been assigned to this repository.
