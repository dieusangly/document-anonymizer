# Open-source document pseudonymization tools

**Survey date:** 12 November 2026. **Scope:** Windows, macOS and Linux;
DOCX/PDF formatting, persistent mappings and identity restoration in AI-generated outputs.

These are assessments of public project documentation, not comparative benchmarks.
No project was independently verified to meet every requirement at production
fidelity. Multilingual models, OCR packs and regional identifier rules provide
different kinds of coverage; none establishes recall on mixed-language documents.
The POC's engine choice is documented separately in [architecture](architecture.md).

## Comparison

| Application | OS / interface | Documents and fidelity | Restoration / mappings | Languages and detection |
| --- | --- | --- | --- | --- |
| **[PII Shield](https://github.com/gregmos/PII-Shield)**, MIT | Windows, macOS, Linux; CLI and Claude integration | DOCX formatting/tracked-change preservation documented; PDF text extraction with text output; scanned-PDF OCR unsupported in the inspected reader | Persistent reusable mappings; text/DOCX and AI-output restoration; configurable retention, reportedly 7 days by default | Offline GLiNER PII Base via ONNX Runtime Node/Transformers.js plus rules. No exhaustive model language list; identifier rules cover UK, DE, FR, IT, ES, CY, FI and EU-wide patterns. Language-specific recall unverified |
| **[DocCloak](https://github.com/WLojek/DocCloak)**, AGPL-3.0 | Windows, macOS, Linux; local browser UI | Formatting-oriented DOCX export; PDF text retained where editable, some pages rasterized; annotations, forms, bookmarks, attachments and metadata removed | AI-response restoration during the session; mappings are memory-only and lost on tab close | Local GLiNER/BardS.ai NER via ONNX WASM, 175+ regex rules and Tesseract WASM. Explicit languages: EN, PL, DE, FR, ES, PT, SV, NO; optional BardS.ai model advertises 24+ EU languages. Mixed-language recall unverified |
| **[Rizzo PII](https://github.com/Rizzo-AI-Academy/rizzo-pii)**, MIT · [Training data](https://github.com/Rizzo-AI-Academy/rizzo-pii/blob/main/docs/DATASET.md) | Windows, macOS Apple Silicon, Linux; Tauri app | Layout-oriented PDF anonymization; native DOCX input and exact PDF structure recovery unverified | Local reversible dictionary, including AI-output restoration | Local CPU inference with a ~0.3B mmBERT/ModernBERT token classifier, rules and checksums. Training languages: IT, EN, FR, DE, ES, NL, HI, TE; Italian is primary. Comparable non-Italian/mixed-language accuracy unverified |
| **[Lethe](https://github.com/moonlight-lupin/lethe)**, Apache-2.0 | Windows, macOS, Linux; GUI, Windows installer or pipx | DOCX/PPTX/XLSX/PDF; PDF-to-DOCX conversion prevents native PDF round trips; fine formatting and embedded content have limits | Encrypted persistent vault; restores placeholders in AI replies and supported files, not original bytes | Local dictionary/regex, optional Presidio/spaCy and Tesseract/PDFium OCR. English initially; configurable models/OCR, including Chinese, Japanese and Korean. Additional downloads and accuracy checks required |
| **[GoCalma](https://github.com/ketchalegend/gocalma)**, MIT | Windows, macOS, Linux; local browser | PDF only, including scans; rasterized anonymized output | Encrypted `.gocalma` recovery file can restore the original PDF; arbitrary AI-output restoration undocumented | Local NER via WebGPU/WASM fallback, rules and OCR. EN, DE, FR, IT, ES; detection accuracy and mixed-language recall unverified |
| **[Nvisy Studio](https://github.com/nvisycom/studio)**, AGPL-3.0 | Windows, macOS, Linux; Tauri/web | Redaction pipelines; exact DOCX/PDF round-trip fidelity unverified | Pseudonymization ecosystem; complete AI-output restoration unverified | Configuration-dependent: hosted API by default or self-hosted backend. Models/languages depend on the backend; translated UI does not establish multilingual detection |
| **[Anonymizer (arcane-tl)](https://github.com/arcane-tl/anonymizer)**, MIT | Windows/macOS installers and CLI; Linux installer unverified | DOCX/PDF, including OCR; native redaction is best effort and needs residual-data/layout checks | Stable placeholders and optional sensitive JSON mapping; complete automatic AI-output restoration undocumented | Local regex, spaCy and OCR by default; optional local Ollama or explicit remote LLM. EN, FI, optional SV; per-document language detection, mixed-language performance unverified. Remote mode is not offline |

Language codes: EN English, FR French, DE German, ES Spanish, IT Italian, NL Dutch,
PL Polish, PT Portuguese, SV Swedish, NO Norwegian, FI Finnish, HI Hindi, TE Telugu.
UK and CY refer to country-specific identifier rules, not language models.

## Evaluation priorities

1. **PII Shield:** DOCX anonymize → AI-edit → restore, mapping persistence and PDF fidelity.
2. **DocCloak:** French/mixed-language recall, retained text layers and session-loss behavior.
3. **Lethe:** Persistent encrypted mappings, non-European languages and PDF conversion losses.
4. **Rizzo PII:** PDF layout, Italian detection and non-Italian/mixed-language recall.
5. **GoCalma:** Exact PDF recovery with a hash comparison; AI-output restoration is a separate capability.

## Acceptance checks for candidate tools

- **Recovery:** Compare file hashes where exact recovery is claimed. Placeholder
  replacement alone does not reconstruct original bytes; an encrypted original may be needed.
- **AI-output restoration:** Restore identities in newly authored/rearranged DOCX
  and PDF content, including malformed-placeholder handling.
- **Formatting:** Inspect fonts, pagination, tables, headers/footers, styles,
  comments, revisions, annotations, bookmarks, forms, OCR layers and signatures.
- **Detection:** Measure false negatives by language, entity type and scan quality
  on French, English and mixed-language documents, plus relevant additional languages.
- **Privacy and persistence:** Inspect offline/network behavior, encrypted mappings,
  cross-session recovery, import/export, backups and retention. A local browser UI
  does not establish local backend processing.

Reversible pseudonymization is not irreversible anonymization; remaining context
can still identify someone. [Piixie](https://piixie.ai/docs/) was excluded from the
open-source comparison because public source code and an open-source license were
not verified, despite its reversible native-format claims.

# Public benchmark datasets (banking and insurance)

**All datasets below use synthetic personal data.** XFUND is the exception in provenance only: its form *templates* are collected from real sources, but their filled-in data is synthetic. None is an open corpus of real client records.

| Dataset | Domain / languages | Provenance | Data and annotations | Best use |
|---|---|---|---|---|
| [Gretel Finance PII](https://huggingface.co/datasets/gretelai/synthetic_pii_finance_multilingual) | Finance; EN/FR + 5 others | Synthetic | 55,940 texts; 29 PII classes and spans | Financial PII detection |
| [Strata Insurance Corpus](https://huggingface.co/datasets/NikolaiSachok/strata-insurance-corpus) | Insurance; EN/FR + 4 others | Synthetic | 1,311 files (PDF/DOCX/JPG etc.); PII index | Multiformat redaction and OCR |
| [PDF-PII-Bench](https://github.com/callixdev/pdf-pii-bench) | Banking + general; EN (US) | Synthetic | 50 PDFs; 1,121 verified PII spans | PDF-level PII scoring |
| [Bankstatemently](https://github.com/bankstatemently/bank-statement-parsing-benchmark) | Bank statements; multiple languages, incl. French (Canada) | Synthetic | Statement PDFs; no public PII-span labels | PDF and layout robustness |
| [Synthetic Financial PII](https://data.mendeley.com/datasets/tzrjx692jy/1) | Finance; primarily EN | Synthetic | Financial texts with PII offsets; ~45k training entries | Finance-specific NER |
| [FR-PII-Bench](https://huggingface.co/datasets/JaqueBill/fr-pii-bench) | Administrative/financial; FR | Synthetic | 300 texts; 13 PII classes and offsets | French recall and false positives |
| [AI4Privacy PII-Masking-200k](https://huggingface.co/datasets/ai4privacy/pii-masking-200k) | General; EN/FR/DE/IT | Synthetic | ~209k texts; 54 PII classes | Multilingual PII regression |
| [OpenPII 1M](https://huggingface.co/datasets/ai4privacy/pii-masking-openpii-1m) | General; EN/FR + 21 others | Synthetic | 1.43m texts; 19 PII classes | Large-scale multilingual detection |
| [NVIDIA Nemotron-PII](https://huggingface.co/datasets/nvidia/Nemotron-PII) | General incl. finance/insurance; EN | Synthetic | 100k texts; 55+ PII/PHI classes | Domain-general NER |
| [XFUND](https://github.com/doc-analysis/XFUND) | Forms; FR + 6 others (no EN) | **Mixed:** real templates, synthetic entries | 199 forms/language; layout labels, **no PII spans** | OCR and layout testing |

**Evaluate separately:** PII recall/precision by type and language; OCR and scan failures; irreversible PDF redaction (including hidden text/metadata); layout fidelity; and reversible mapping/re-identification. Text-span benchmarks alone cannot validate secure document redaction.

