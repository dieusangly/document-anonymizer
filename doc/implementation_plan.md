# POC requirements and implementation plan

## Objective and scope

Build a local Streamlit application for reversible **pseudonymization** of banking
and insurance documents. Users must be able to select/upload a document, review
sensitive-data detections, anonymize, preview/download, then restore and download
original visible information. Preserve formatting where feasible; byte-identical
file recovery is not required.

The original scope is text-based PDF and DOCX in French, English and mixed-language
text. OCR and complex-document handling were added later; current support and
limits are in the [runbook](../README.md#boundaries), with completion evidence in
[validation](validation.md).

| Information | Required categories |
| --- | --- |
| Personal | Names, addresses, birth dates, phone numbers, emails |
| Banking | IBAN, BIC, account numbers, customer identifiers |
| Insurance | Policy numbers, claim references, beneficiaries |
| Other | National identifiers, health information and contextually sensitive values |

Use stable, type-specific placeholders such as `[PERSON_001]` and `[IBAN_001]`.
Category coverage is a requirement, not a guarantee of detection in arbitrary layouts.

## Implementation approach

1. **Select an existing open-source engine.** Start with the
   [survey](state_of_the_art.md); assess offline operation, French/English detection,
   document fidelity, persistent restoration, Python integration and licensing.
   Keep the assessment lightweight and add custom rules only where needed.
   Record the selection in [architecture](architecture.md).
2. **Separate processing, detection, mappings and UI.** Use Python, Streamlit, a root
   `.venv` and `requirements.txt`; avoid unnecessary services and abstractions.
   Configuration may use environment variables or an optional `.envrc`.
3. **Implement review and replacement.** Show detected entities, allow manual
   corrections, replace selected values consistently within a case, and provide
   previews and downloads.
4. **Persist encrypted mappings.** Generate a local key unless one is configured;
   support restoration after restart and across related documents. Report missing
   mappings rather than guessing values.
5. **Generate fixtures and validate end to end.** Use the corpus and acceptance
   checks below. Document installation, the chosen engine, results and limitations.

## Privacy requirements

- Process locally without external APIs, telemetry, uploads or API keys.
- Remove/replace sensitive text, rather than merely covering it visually.
- Avoid leaking originals through metadata, hidden content or logs.
- Keep secrets, generated files and mappings out of Git.
- Reject unsafe or unsupported inputs with clear errors.
- Explain that reversible pseudonymization is not irreversible anonymization.

## Synthetic corpus

Generate at least four realistic fictional documents, selectable in the UI:

| Document | Format | Language |
| --- | --- | --- |
| Bank statement | PDF | French |
| Client onboarding form | DOCX | English |
| Insurance claim | PDF | French |
| Insurance contract | DOCX | French/English |

Include the required sensitive categories, dates and repeated identities, with
independent expected annotations for detection tests.

## Acceptance criteria

- All four documents complete anonymize → preview/download → restore → preview/download.
- Repeated values and related documents share consistent case placeholders.
- Restoration works after restart; missing mappings and unsupported inputs fail clearly.
- Selected originals are absent from exported text, underlying objects and image pixels.
- Detection precision/recall are measured on annotated fixtures, with limitations stated.
- Readability and formatting are checked visually; automated end-to-end tests pass.
- Installation, launch instructions, engine rationale and validation results are documented.

Prioritize a reproducible end-to-end POC. Handwriting recognition, batch processing
and cloud integration are outside the completion criteria.
