# POC validation

Environment: Linux, Python 3.11.11, Chromium 159, Tesseract English/French data and
LibreOffice. The POC workflow is implemented within the
[documented boundaries](../README.md#boundaries); arbitrary-document detection and
exact format recovery are not claimed.

## Automated checks

On 18 November 2026, **all 63 tests passed in 381.21 seconds**: 53 processing/mapping
tests, one Streamlit AppTest and nine Chromium cases. Ruff lint/formatting and
local documentation link/whitespace checks also passed. One upstream
pytest-playwright fixture deprecation warning remains; it is not an application failure.

| Coverage | Evidence |
| --- | --- |
| Synthetic round trips | All four fixtures restore exact extracted text, including tables and headers/footers |
| Persistence and mappings | Separate-process and browser/server restart restoration; stable case tokens, wrong-case guards, encrypted files, permissions, concurrent writers, missing/wrong keys and corruption |
| Export privacy | Selected values absent from extracted text, decoded PDF streams and DOCX/XML; source authors and custom XML removed |
| Rendered PDFs | Images, scans, links, forms, annotations, rotation, vectors and covered/hidden text; independent OCR checks output pages and extracted image pixels |
| Complex DOCX | Images, merged tables, hyperlinks and multiple sections convert to PDF and restore extracted text; case marker retained |
| Local processing | Cold detector initialization and four workflows with Python socket connections blocked; landing and original-document browser checks record no external HTTP requests |
| Conversion isolation | HTTP sentinel receives no linked-image request; INCLUDETEXT cannot read a local sentinel file |
| Failure handling | Invalid/encrypted files and macros rejected; missing dependencies explained; missing/malformed mappings prevent partial restoration |
| Review and UI | Manual additions, split Word runs, invalidated stale downloads, unlabeled French/English names, uploads/downloads, default upload screen, no sidebar/menu, desktop/mobile bounds |

Run the [test commands](../README.md#tests). Browser validation uses Playwright
with temporary loopback servers, vaults, logs, screenshots and downloads. For a
custom browser cache, set `PLAYWRIGHT_BROWSERS_PATH` consistently during Chromium
installation and testing; this environment uses `/tmp/document-anonymizer-browsers`.

## Detection benchmark

Exact start/end offsets and entity types must match independent fixture
annotations in `data/synthetic/annotations.json`; repeated mentions count separately.

| Document | Language | True positives | False positives | False negatives |
| --- | --- | ---: | ---: | ---: |
| Bank statement PDF | French | 10 | 0 | 0 |
| Onboarding DOCX | English | 12 | 0 | 0 |
| Insurance claim PDF | French | 10 | 0 | 0 |
| Insurance contract DOCX | French/English | 12 | 0 | 0 |
| **Total** | | **44** | **0** | **0** |

**Precision: 100%. Recall: 100%.** All 13 annotated types and each language group
have the same score. The benchmark command emits document, language and entity-type
metrics as JSON. Credit cards and manual `OTHER` entities are absent from this corpus;
two additional unlabeled name/email test sentences are excluded from these metrics.

These four small, mostly labeled development fixtures demonstrate regression
coverage, not held-out or real-world accuracy. The supplied invoice processed and
restored its extracted text, but detection found only two email occurrences,
leaving address and other sensitive fields unselected.

## Visual checks

Earlier visual inspection covered all 12 original/anonymized/restored synthetic
variants: one page each, readable text without overlap or clipping. PDF variants
were rasterized with PyMuPDF; DOCX variants were rendered with LibreOffice.
The invoice retained its logo and readable layout after selected replacements.
Complex PDF/DOCX browser flows were inspected at 1280×720.

The charcoal UI was inspected at 1440×1000 and 390×844 for text/input contrast,
spacing and overflow. Browser tests check responsive bounds and reject application
exceptions or console errors in the landing and simple/complex round trips.
QA images are temporary test artifacts, not repository deliverables. Fidelity
tradeoffs and detection gaps are listed in the [runbook](../README.md#boundaries).
