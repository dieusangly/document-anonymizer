# Document Anonymizer

A local Streamlit POC for reversible **pseudonymization** of French, English and
mixed-language banking and insurance documents. Detect sensitive text, review
replacements and restore original values using encrypted mappings, even after a restart.

## Install and launch

Tested on Linux with Python 3.11. Run commands from the repository root.
Installation requires internet access; document processing requires no network,
API keys, GPU, Microsoft Word or database server.

For scans, images and complex layouts, install Tesseract and LibreOffice Writer:

```bash
# Ubuntu / Debian
sudo apt-get install tesseract-ocr tesseract-ocr-eng tesseract-ocr-fra libreoffice-writer
```

On other systems, put `tesseract` and `libreoffice` (or `soffice`) on `PATH`.
Verify with `tesseract --list-langs` (must include `eng` and `fra`) and
`libreoffice --version`. The simple synthetic examples work without these tools.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m anonymizer.dataset
python -m streamlit run app.py
```

Open **http://127.0.0.1:8501**. Samples also generate automatically when first
selected. Restart Streamlit after code or configuration changes; file watching
is disabled. The single requirements file includes test and lint tools.

For `uv`, replace the environment creation and package installation commands with:

```bash
uv venv .venv --python 3.11
uv pip install --python .venv/bin/python -r requirements.txt
source .venv/bin/activate
```

## Use

1. Optionally enter a non-sensitive **Document reference**, such as `client-2026`.
   Blank uses the default mappings (`demo-case`). Reuse the reference for related documents.
2. Upload a PDF/DOCX or enable **Use a sample document**.
3. Review detections: uncheck false positives or change entity types. In
   **Add a missed value**, enter one exact value per line and select a type.
   Each value must fit within one paragraph or PDF line; the type applies to all
   manual entries. Selections replace every exact occurrence, but do not train the detector.
4. Click **Anonymize**, review the preview and download the result.
5. Click **Reverse Anonymize** to preview and download restored content.
   After a restart, select that operation, enter the same document reference and
   upload the anonymized file.

PDF previews show pages; DOCX previews show text in reading order. Open Word
outputs in Word or LibreOffice to inspect formatting. Download filenames are
generic to avoid disclosing source filenames.

## Configuration and mappings

- [detection.py](anonymizer/detection.py): entity types, field-label rules and
  confidence threshold. There is no detection-settings screen or separate policy file.
- [.streamlit/config.toml](.streamlit/config.toml): theme and local server settings.
- `ANONYMIZER_DATA_DIR`: optional vault directory; default `.local/vault/`, ignored by Git.
- `ANONYMIZER_KEY`: optional Fernet key; otherwise a key is generated in the vault.

Back up **both the vault and its key**. Back up an environment key separately;
never change the key for an existing vault. Loss of either prevents restoration.
Anyone with both can decrypt the mappings. The app is for one trusted local user
and binds to loopback; it has no multi-user authentication or key-rotation service.

Uploads and results stay in process/browser memory during the session. Complex
DOCX conversion uses a private temporary directory, removed on completion or
failure; forced termination can leave files behind. Closing the browser does not
erase persistent mappings. Downloads remain under your control. There is no
automatic retention policy or secure-erasure guarantee.

## Tests

```bash
source .venv/bin/activate
python -m playwright install chromium
python -m pytest -q
python -m scripts.benchmark
ruff check anonymizer app.py scripts tests
ruff format --check anonymizer app.py scripts tests
```

Chromium may also need OS libraries: `python -m playwright install-deps chromium`.
For core tests without Chromium, run `python -m pytest -q -m 'not browser'`.
Tests use temporary fixtures, vaults and local Streamlit servers, never the user's
vault. See [validation results](doc/validation.md) for coverage and benchmark limits.

## Boundaries

This is reversible pseudonymization, not irreversible anonymization. Review the
extracted text and every output page before sharing.

**Detection:** Names use local NER and bilingual labels. Addresses, birth dates,
medical descriptions and domain IDs rely heavily on labels. Unlabeled multiline
addresses, company names, tax identifiers, health context, single-word names and
wrapped fields can be missed. Manual corrections are available. Spelling, spacing
and capitalization variants are distinct; exact values reuse placeholders within a case.

**Formats:** Simple DOCX files retain editable text, tables, headers/footers and
basic formatting. Complex DOCX files (images, links, merged cells or multiple
sections) are converted locally and **download as PDF**, with a UI notice.
Cached field values remain; live fields are not updated.

PDF images, scans, links, rotations, vector graphics, forms and visible annotations
use rendered-page processing. English/French OCR reads image text; native visible
text is reused where possible. Recognized text pixels are erased before writing
replacement text. Links, attachments, annotation comments, hidden source layers
and original metadata are not copied; forms lose interactivity and digital
signatures are not preserved as valid signatures.

**Fidelity:** Rendered exports preserve page geometry and graphics, but use standard
fonts and white backgrounds behind reconstructed text; long placeholders can shrink.
Word custom styles and exact pagination are not guaranteed. Replacements inherit
the first character's formatting. Restoration recovers extracted text, including
OCR errors, not original bytes, mixed formatting, interactive features or metadata.

**OCR and graphics:** Handwriting, low-resolution scans, rotated/small text and
other languages can be misread or missed. Photos, signatures and QR/barcodes
remain graphics and are **not automatically anonymized**. Unsupported characters
or dense replacement layouts can fail. Arbitrary-file support is not guaranteed;
this is not a sanitizer for every malicious document.

**Input limits:** 10 MB, 200,000 extracted characters, 30 PDF pages, page dimensions
up to 1500 points and 120 megapixels total in rendered mode. DOCX packages are
limited to 500 entries and 40 MB expanded. OCR has a 90-second timeout per page;
Word conversion has a 90-second timeout. Encrypted/damaged files and DOCX
macros/ActiveX are rejected.

**Restoration:** Missing or malformed mappings block restoration. Newly authored
PDF/DOCX files containing known placeholders can be restored with the same case;
without the app's case marker, their provenance cannot be checked.

See [architecture and component tools](doc/architecture.md),
[POC requirements](doc/implementation_plan.md) and the
[open-source tool survey](doc/state_of_the_art.md).
