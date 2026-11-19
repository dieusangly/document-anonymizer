# POC validation

Environment: Linux, Python 3.11.11, Chromium 159, Tesseract English/French data and
LibreOffice. The POC workflow is implemented within the
[documented boundaries](../README.md#boundaries); arbitrary-document detection and
exact format recovery are not claimed.

## Automated checks

On 18 November 2026, **all 95 tests passed in 317.51 seconds**, including 20
rendered-document tests and nine Chromium workflows. One upstream pytest fixture
deprecation warning remains. Ruff lint/formatting, Node preload-guard syntax,
package/lockfile consistency and documentation links also pass.

Setup and offline inference are verified with Node.js 22.23.5 and PII Shield 2.2.0.

| Coverage | Evidence |
| --- | --- |
| Synthetic round trips | All four fixtures restore exact extracted text, including tables and headers/footers |
| Persistence and mappings | Separate-process and browser/server restart restoration; stable case tokens, wrong-case guards, encrypted files, permissions, concurrent writers, missing/wrong keys and corruption |
| Export privacy | Selected values absent from extracted text, decoded PDF streams and DOCX/XML; source authors and custom XML removed |
| Rendered PDFs | Images, scans, links, forms, annotations, rotation, vectors and covered/hidden text; OCR/native table columns, overlapping OCR fragments and unchanged logo pixels; independent OCR checks output pages and extracted image pixels |
| Complex DOCX | Images, merged tables, hyperlinks and multiple sections convert to PDF and restore extracted text; case marker retained |
| Local processing | Cold detector initialization and four workflows with Python socket connections blocked; landing and original-document browser checks record no external HTTP requests |
| Conversion isolation | HTTP sentinel receives no linked-image request; INCLUDETEXT cannot read a local sentinel file |
| Failure handling | Invalid/encrypted files and macros rejected; missing dependencies explained; missing/malformed mappings prevent partial restoration |
| Review and UI | Manual additions, split Word runs, invalidated stale downloads, unlabeled French/English names, uploads/downloads, default upload screen, no sidebar/menu, desktop/mobile bounds |
| Engine boundary | UTF-16/emoji offsets, multiline addresses, normalized upstream whitespace, invalid spans, missing setup, failed/partial inference, timeouts and blocked scan-time network/bootstrap |

Run the [test commands](../README.md#tests). Browser validation uses Playwright
with temporary loopback servers, vaults, logs, screenshots and downloads. For a
custom browser cache, set `PLAYWRIGHT_BROWSERS_PATH` consistently during Chromium
installation and testing; this environment uses `/tmp/document-anonymizer-browsers`.

## Detection benchmark

Exact start/end offsets and entity types must match independent fixture
annotations in `data/synthetic/annotations.json`; repeated mentions count separately.

| Document | Language | True positives | False positives | False negatives |
| --- | --- | ---: | ---: | ---: |
| Bank statement PDF | French | 10 | 1 | 0 |
| Onboarding DOCX | English | 12 | 0 | 0 |
| Insurance claim PDF | French | 10 | 1 | 0 |
| Insurance contract DOCX | French/English | 12 | 0 | 0 |
| **Total** | | **44** | **2** | **0** |

**Precision: 95.7%. Recall: 100%.** Results use PII Shield's tuned label set,
NER/minimum thresholds of 0.20, and the app's supplemental field/contact/postal
rules. The two extra predictions select an amount as a phone number and a date as
a person. The round-trip tests require all annotated spans, while the benchmark
reports additional predictions separately. Per-language/type metrics are emitted
as JSON by `python -m scripts.benchmark`.

The corpus contains 13 annotated types; credit cards, manual `OTHER`, organizations
and the regional identifier types are absent from its expected labels. Unlabeled
name/email, invoice-address and Unicode cases are tested separately. These four
small, mostly labeled development fixtures demonstrate regression coverage, not
held-out or real-world accuracy; French model quality is not established by this score.

## Supplied-document checks

Checks use temporary vaults; private documents and mappings are not stored in the
repository. These results verify selected replacements, not complete PII detection.

**Invoice:** The detector selected 15 line spans: 11 addresses (including the
standalone “Dublin” line), one organization, two emails and one EU VAT identifier.
Independent pixel OCR found none of the selected originals; restoration recovered
the extracted text. Address expansion can include headings/company text. An Irish
VAT identifier with two trailing letters, invoice numbers and dates were missed.

**Two-page bank statement:** All 17 selected occurrences restored without remaining
placeholders. All 54 checked amount cells retained their column positions, and the
bank logo's image pixels were identical in both exports. A standalone French
customer name was missed. Previously distorted exports need regeneration from
the original document.

**Chinese text:** A separate five-page English/Chinese statement showed Chinese
labels and a paragraph corrupted during import. Watermark bounds exclude valid
native text, then English/French OCR misreads it. Successful mapping restoration
does not establish Chinese fidelity or recover text lost before detection. This
limitation remains unresolved; see [OCR support](../README.md#boundaries).

## Visual checks

Visual inspection covered all 12 original/anonymized/restored synthetic
variants: one page each, readable text without overlap or clipping. PDF variants
were rasterized with PyMuPDF; DOCX variants were rendered with LibreOffice.
The invoice retained its logo and readable layout after selected replacements.
Complex PDF/DOCX browser flows were inspected at 1280×720.

The charcoal UI was inspected at 1440×1000 and 390×844 for text/input contrast,
spacing and overflow. Browser tests check responsive bounds and reject application
exceptions or console errors in the landing and simple/complex round trips.
QA images are temporary test artifacts, not repository deliverables. Fidelity
tradeoffs and detection gaps are listed in the [runbook](../README.md#boundaries).
