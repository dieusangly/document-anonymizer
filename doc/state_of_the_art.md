# Open-source document anonymization and de-anonymization tools

**Updated:** 12 November 2026  
**Scope:** Windows, macOS and Linux; priority is reversible pseudonymization of **DOCX/PDF**, restoration of identities in **AI-generated outputs**, persistent mappings, and preservation of document formatting.

> **Bottom line:** None of the projects has been independently verified to satisfy *all* these requirements at production-grade fidelity. "Multilingual" means the detection stack can process more than one language; it does **not** establish high recall on mixed-language documents. Assessments below are qualitative judgments based on public project documentation, not comparative benchmarks.

## Comparison

| Application | OS / interface | DOCX/PDF support and format preservation | Restoration / mapping | Supported languages | Multilingual capacity / language assessment | Local processing / detection engine | License / source |
|---|---|---|---|---|---|---|---|
| **PII Shield** | Windows, macOS, Linux; CLI and Claude integration | DOCX: documented formatting and tracked-change preservation. PDF: supported, but native layout/structure fidelity not established. | Persistent reusable mappings; de-anonymizes text and DOCX, including AI outputs; configurable retention (default reportedly 7 days). | Multilingual NER (no exhaustive language list published); country-specific ID rules for UK, DE, FR, IT, ES, CY, FI and EU-wide patterns. | **Promising** for mixed-language European text, but language-specific NER accuracy and mixed-language recall unverified. Identifier-rule coverage must not be mistaken for full linguistic coverage. | **Yes**, including offline CLI; GLiNER PII Base using ONNX Runtime Node and Transformers.js, plus regex/identifier rules. | MIT · [GitHub](https://github.com/gregmos/PII-Shield) |
| **DocCloak** | Windows, macOS, Linux; local/browser-based UI | DOCX: formatting-oriented export. PDF: text layer retained where safely editable; some pages rasterized; annotations, forms, bookmarks, attachments and metadata removed. | Restores AI responses while session is open; identity mappings are **memory-only** and lost when tab closes. | Explicit UI/detection languages: EN, PL, DE, FR, ES, PT, SV, NO; optional BardS.ai EU PII model advertises **24+ EU languages**. | **Strong European-language candidate**; selectable multilingual GLiNER/BardS.ai models and regional rules. Mixed-language accuracy still needs validation. | **Yes**, in browser after initial model download; GLiNER and BardS.ai NER via ONNX Runtime WebAssembly, 175+ regex rules, Tesseract WASM OCR. | AGPL-3.0 · [GitHub](https://github.com/WLojek/DocCloak) |
| **Rizzo PII** | Windows, macOS (Apple Silicon), Linux; native Tauri app | PDF: direct layout-oriented anonymization; no native DOCX input documented; exact PDF structure recovery unverified. | Local reversible dictionary, including restoration of identities in AI outputs. | IT, EN, FR, DE, ES, NL, HI, TE (training data); **Italian is the primary target**. | **Excellent Italian focus**, promising but less validated elsewhere; multilingual training is documented, yet mixed-language performance and non-Italian accuracy are not established by comparable benchmarks. | **Yes**, bundled local CPU inference; ~0.3B-parameter mmBERT/ModernBERT token classifier, with rules and checksum checks. | MIT · [GitHub](https://github.com/Rizzo-AI-Academy/rizzo-pii) |
| **Lethe** | Windows, macOS, Linux; local GUI (Windows installer, pipx cross-platform) | DOCX, PPTX, XLSX and PDF input; PDF conversion to DOCX prevents native PDF round-trip; possible fine-formatting loss; embedded content limitations. | **Encrypted persistent vault**; can restore placeholders in AI replies and other supported files; does not guarantee byte-identical original recovery. | English initially; configurable additional NLP and OCR languages, explicitly including Chinese, Japanese and Korean; customizable dictionary works across languages. | **Most configurable for diverse scripts**; extra language-model downloads needed; multilingual and mixed-script detection quality requires testing. | **Yes**; dictionary + regex; optional Microsoft Presidio/spaCy NER, Tesseract/PDFium OCR. | Apache-2.0 · [GitHub](https://github.com/moonlight-lupin/lethe) |
| **GoCalma** | Windows, macOS, Linux; local browser | PDF only, including scans; anonymized PDF is rasterized; encrypted recovery file can restore the original PDF. | **Exact original PDF recovery** via encrypted `.gocalma` file; restoration in arbitrary AI-generated outputs not documented. | EN, DE, FR, IT, ES (including local OCR data). | **Good for five European languages**; mixed-language recognition and detection accuracy need validation. | **Yes**, in browser; local NER with WebGPU/WASM fallback, rules, and local OCR. | MIT · [GitHub](https://github.com/ketchalegend/gocalma) |
| **Nvisy Studio** | Windows, macOS, Linux; Tauri desktop and web app | Document redaction pipelines; exact DOCX/PDF round-trip preservation not verified. | Pseudonymization ecosystem; complete AI-output re-identification workflow not verified. | Not clearly specified for a standard deployment; depends on backend components. | **Unverified**; do not assume multilingual PII detection from an internationalized user interface. | **Configuration-dependent**: desktop shell connects to hosted API by default or a self-hosted server; specific detection models depend on backend. | AGPL-3.0 · [GitHub](https://github.com/nvisycom/studio) |
| **Anonymizer (arcane-tl)** | Windows, macOS installers; CLI; Linux installer not established | DOCX, PDF (including scanned PDF OCR); native redaction is best effort and requires checking residual data and formatting. | Stable placeholder generation and optional sensitive JSON mapping; automatic complete AI-output restoration not documented. | EN, FI; optional SV model/detection support. | **Limited** for broad multilingual documents; English/Finnish focus and per-document language detection, with intra-document mixing not validated. | **Yes by default**; regex/patterns, spaCy NER and OCR; optional local Ollama or explicit remote LLM integration (remote mode is **not** offline). | MIT · [GitHub](https://github.com/arcane-tl/anonymizer) |

**Language abbreviations:** EN English; FR French; DE German; ES Spanish; IT Italian; NL Dutch; PL Polish; PT Portuguese; SV Swedish; NO Norwegian; FI Finnish; HI Hindi; TE Telugu; CY Cyprus (in this table, country-specific rules rather than a linguistic model). "Supported languages" can refer to models, training languages, OCR packs, or identifier rules; the table distinguishes these wherever possible.

## Recommended evaluation order

1. **PII Shield — DOCX restoration first.** Verify the format-preserving DOCX anonymize → AI-edit → restore cycle, mapping persistence, and mixed French/English detection. Separately inspect PDF fidelity.
2. **DocCloak — DOCX/PDF and multilingual detection first.** Compare French and mixed-language recall, preserved text layers, visual formatting, and what happens after the browser session closes.
3. **Lethe — long-lived encrypted mapping first.** Test persistent restoration, configured non-European languages, and the loss introduced by PDF-to-DOCX conversion.
4. **Rizzo PII — PDF and Italian documents first.** Check the PDF visual result, non-Italian recall, and mixed-language documents.
5. **GoCalma — exact original PDF recovery first.** Verify decryption and file-hash matching, but do not assume AI-output restoration.

## Non-negotiable acceptance tests

- **Original recovery:** Recover the original file with a hash match where possible. Token replacement alone is not byte-identical file restoration; retaining an encrypted original is often necessary.
- **AI-output restoration:** Restore identities in newly authored or rearranged AI output, including edited DOCX/PDF files—not only pasted plain text—and test malformed placeholders.
- **Format preservation:** Compare typography, pagination, tables, headers/footers, styles, comments, tracked changes, annotations, bookmarks, forms, text/OCR layers, embedded fonts and digital signatures.
- **Language accuracy:** Test French, English, and a single French/English mixed document; add language combinations relevant to your usage. Measure false negatives separately by language, PII type, and scan/OCR quality.
- **Privacy and persistence:** Work offline after models are installed; inspect network traffic, mapping encryption, cross-session recovery, import/export, backups, and retention rules. A "local browser" front end does not automatically mean all backend processing is local.

**Important:** Reversible pseudonymization is not irreversible anonymization under GDPR. Unmasked contextual information can still identify someone.

**Not included as confirmed open source:** [Piixie](https://piixie.ai/docs/) — interesting reversible native-format claims, but publicly available source code and an open-source license were not verified.

## Project documentation

- [PII Shield](https://github.com/gregmos/PII-Shield)
- [DocCloak](https://github.com/WLojek/DocCloak)
- [Rizzo PII](https://github.com/Rizzo-AI-Academy/rizzo-pii) · [Training language breakdown](https://github.com/Rizzo-AI-Academy/rizzo-pii/blob/main/docs/DATASET.md)
- [Lethe](https://github.com/moonlight-lupin/lethe)
- [GoCalma](https://github.com/ketchalegend/gocalma)
- [Nvisy Studio](https://github.com/nvisycom/studio)
- [Anonymizer](https://github.com/arcane-tl/anonymizer)
