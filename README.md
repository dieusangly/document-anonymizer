# Document Anonymizer

A local Streamlit interface for **PII Shield** and reversible pseudonymization of
French, English and mixed-language banking/insurance documents. Review detections,
replace sensitive text and restore original values using encrypted mappings.

## Install and launch

Tested on Linux with Python 3.11 and Node.js 22. Run from the repository root.
Installation needs internet access; processing needs no network, API keys, GPU,
Microsoft Word or database server.

For scans, images and complex layouts, install Tesseract and LibreOffice Writer:

```bash
# Ubuntu / Debian
sudo apt-get install tesseract-ocr tesseract-ocr-eng tesseract-ocr-fra libreoffice-writer
```

On other systems, put `tesseract` and `libreoffice` (or `soffice`) on `PATH`.
Verify with `tesseract --list-langs` (must include `eng` and `fra`) and
`libreoffice --version`. Simple synthetic examples work without these tools.

Install Node.js 22+ and npm before setup. If the system Node is older, install a
local runtime; the app and setup command use it automatically:

```bash
npm install --prefix .local/node node@22.23.5
```

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
npm ci --ignore-scripts
python -m scripts.setup_pii_shield
python -m anonymizer.dataset
python -m streamlit run app.py
```

Open **http://127.0.0.1:8501**. Setup downloads the ~634 MB GLiNER model and
initializes inference dependencies once; allow several minutes and roughly 3 GB
of disk space. Samples also generate automatically when first selected. Restart
Streamlit after code/configuration changes; file watching is disabled.

`requirements.txt` includes Python test/lint tools; `package-lock.json` pins Node
dependencies. Existing environments can reinstall requirements; Presidio/spaCy
are no longer required, and existing encrypted vaults remain usable.

For `uv`, replace environment creation and Python package installation with:

```bash
uv venv .venv --python 3.11
uv pip install --python .venv/bin/python -r requirements.txt
source .venv/bin/activate
```

## Use

1. Enter an optional, non-sensitive **Document reference**, such as `client-2026`.
   Reuse it for related documents. Blank uses the shared default `demo-case`;
   it does not generate a unique reference per document.
2. Upload a PDF/DOCX or enable **Use a sample document**.
3. Review detections: uncheck false positives or change types. In **Add a missed
   value**, enter one exact value per line and select a type for all manual entries.
   Each value must fit within one paragraph/PDF line. Selections replace every
   exact occurrence; manual corrections do not train the detector.
4. Click **Anonymize**, review the preview and download the result.
5. Click **Reverse Anonymize** to restore. After a restart, select that operation,
   enter the same document reference and upload the anonymized file.

PDF previews show pages; DOCX previews show reading-order text. Open Word outputs
in Word or LibreOffice to inspect formatting. Downloads use generic filenames to
avoid disclosing source filenames.

## Configuration and mappings

- [detection.py](anonymizer/detection.py): entity types and supplemental field,
  contact and postal rules. There is no detection-settings screen.
- `PII_NER_LABEL_SET`: `tuned` (default), `compact` or `extended`.
- `PII_NER_THRESHOLD` and `PII_MIN_SCORE`: default `0.20`; lower values favor recall
  and can increase false positives. Set before launch, then restart.
- `ANONYMIZER_ENGINE_DIR`: model/dependency directory; default `.local/pii-shield/`.
- `ANONYMIZER_NODE`: optional Node.js executable path.
- [.streamlit/config.toml](.streamlit/config.toml): theme and local server settings.
- `ANONYMIZER_DATA_DIR`: vault directory; default `.local/vault/`, ignored by Git.
- `ANONYMIZER_KEY`: optional Fernet key; otherwise generated in the vault.

Each reference has independent mappings. An exact original value reuses its
placeholder; a new value gets the next unused number for its type. Locked, atomic
writes prevent conflicting assignments. Restoration mappings live in the encrypted
vault rather than the output document. PII Shield's session mappings and retention
policy are not used.

Back up **both the vault and its key**, including an environment key if configured.
Never change the key for an existing vault; losing either prevents restoration.
Anyone with both can decrypt mappings. The app binds to loopback for one trusted
local user; it has no multi-user authentication or key-rotation service.

Uploads/results remain in session memory. Detection text/diagnostics and complex
DOCX conversion use private temporary directories, removed on completion/failure;
forced termination can leave files behind. Closing the browser does not erase
persistent mappings. Downloads remain under your control. There is no automatic
retention policy or secure-erasure guarantee.

## Tests

```bash
source .venv/bin/activate
python -m playwright install chromium
python -m pytest -q
python -m scripts.benchmark
ruff check anonymizer app.py scripts tests
ruff format --check anonymizer app.py scripts tests
```

Chromium may need OS libraries: `python -m playwright install-deps chromium`.
For core tests without Chromium, run `python -m pytest -q -m 'not browser'`.
Tests use temporary fixtures, vaults and local Streamlit servers, never the user's
vault. See [validation](doc/validation.md) for coverage and benchmark limits.

## Boundaries

This is reversible pseudonymization, not irreversible anonymization. Review the
extracted text and every output page before sharing.

**Detection:** PII Shield combines GLiNER names/organizations/addresses with
identifier patterns. Supplemental rules cover bilingual fields/contact names,
English/French street lines, French/UK city-postcode lines and Irish Eircodes.
Short capitalized city/country lines are included within four lines after a
street/postcode, stopping at blanks, field labels, common headings or prose.
Multiline detections become individual line replacements.

Dates, health descriptions and domain IDs depend heavily on context/labels.
Unlabeled names, address lines and regional identifiers can be missed; the model
can also select non-sensitive dates, amounts or labels. Spelling, spacing and case
variants remain distinct. Use manual corrections for missed values.

**Formats:** Simple DOCX files retain editable text, tables, headers/footers and
basic formatting. Complex DOCX files (images, links, merged cells or multiple
sections) convert locally and **download as PDF**, with a UI notice. Cached field
values remain; live fields are not updated.

PDF images, scans, links, rotations, vectors, forms and visible annotations use
rendered-page processing. English/French OCR reads image text; native visible text
is reused where possible. Table columns are positioned separately; unchanged OCR
regions retain their pixels. Selected text pixels are erased before replacements
are drawn. Links, attachments, annotation comments, hidden source layers and
original metadata are removed; forms lose interactivity and signatures lose validity.

**Fidelity:** Rendered exports preserve geometry/graphics but use standard fonts
and white backgrounds behind reconstructed text; long placeholders can shrink.
Word custom styles and exact pagination are not guaranteed. Replacements inherit
the first character's formatting. Restoration recovers extracted text, including
OCR errors, not original bytes, mixed formatting, interactive features or metadata.

**OCR and graphics:** OCR supports English/French only. Chinese and other languages,
handwriting, low-resolution scans and rotated/small text can be missed or corrupted.
Restoration cannot repair text misread during import. Photos, signatures and
QR/barcodes remain graphics and are **not automatically anonymized**. Unsupported
characters or dense replacement layouts can fail. Arbitrary-file support is not
guaranteed; this is not a sanitizer for every malicious document.

**Input limits:** 10 MB, 200,000 extracted characters, 30 PDF pages, page dimensions
up to 1500 points and 120 megapixels total in rendered mode. DOCX packages allow
500 entries/40 MB expanded. Timeouts: 90 seconds per OCR page, 90 seconds for Word
conversion and five minutes for detection. Model initialization or inference
failure rejects the scan. Encrypted/damaged files and DOCX macros/ActiveX are rejected.

**Restoration:** Missing/malformed mappings block restoration. Newly authored
PDF/DOCX files with known placeholders can be restored using the same reference.
The app's case marker rejects the wrong reference; if another tool removes it,
using the wrong reference can restore incorrect values for matching placeholders.

See [architecture and component tools](doc/architecture.md),
[POC requirements](doc/implementation_plan.md) and the
[open-source tool survey](doc/state_of_the_art.md).
