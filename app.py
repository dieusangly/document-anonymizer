"""Run with: streamlit run app.py"""

from hashlib import sha256
from pathlib import Path

import streamlit as st

from anonymizer.dataset import generate
from anonymizer.detection import TYPES, Detector, Entity
from anonymizer.documents import load_document, preview_pdf
from anonymizer.errors import AnonymizerError
from anonymizer.service import anonymize, restore
from anonymizer.vault import Vault

st.set_page_config(
    page_title="Document Anonymizer", page_icon=":material/verified_user:", layout="wide"
)
st.html(Path(__file__).parent / "assets" / "app.css")


@st.cache_resource
def detector():
    return Detector()


def preview(data, kind, text, label):
    st.subheader(label)
    if kind == "pdf":
        for index, page in enumerate(preview_pdf(data)):
            st.image(page, caption=f"Page {index + 1}", width="stretch")
    else:
        st.caption(
            "Text preview in reading order, including tables and headers/footers. Download to view Word formatting."
        )
    with st.expander(label + " text", expanded=kind == "docx"):
        st.text(text)


def download(result, label, prefix):
    mime = (
        "application/pdf"
        if result.kind == "pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    st.download_button(
        label,
        result.data,
        file_name=prefix + "." + result.kind,
        mime=mime,
        key="download_" + prefix,
    )


def main():
    st.title("Document Anonymizer")
    st.html(
        '<p class="app-intro">Protect sensitive information. Keep your documents useful.</p>'
        '<div class="app-details">Local processing &nbsp;·&nbsp; Encrypted mappings &nbsp;·&nbsp; PDF &amp; Word</div>'
    )
    vault = Vault()
    data = None
    filename = ""
    with st.container(border=True, key="document_panel"):
        operation, reference = st.columns([1.2, 1], gap="large", vertical_alignment="bottom")
        with operation:
            mode = st.radio("Operation", ["Anonymize", "Reverse Anonymize"], horizontal=True)
        with reference:
            case = (
                st.text_input(
                    "Document reference",
                    placeholder="Optional · e.g. client-2026",
                    help="Use the same reference for related documents and restoration. "
                    "Leave blank to use your existing default mappings. Use an alias, not a person's name.",
                ).strip()
                or "demo-case"
            )
        st.divider()
        if mode == "Anonymize":
            st.subheader("Choose a document")
            if st.toggle("Use a sample document", key="use_sample"):
                directory = Path(__file__).parent / "data" / "synthetic"
                if not (directory / "annotations.json").exists():
                    generate(directory)
                files = sorted(directory.glob("*.pdf")) + sorted(directory.glob("*.docx"))
                path = st.selectbox("Sample document", files, format_func=lambda p: p.name)
                data, filename = path.read_bytes(), path.name
                st.caption("Sample documents contain fictional information.")
            else:
                uploaded = st.file_uploader(
                    "Upload PDF or DOCX", type=["pdf", "docx"], key="source_upload"
                )
                if uploaded:
                    data, filename = uploaded.getvalue(), uploaded.name
            st.caption(
                "Review detected values before sharing. You can restore them later using your saved mappings."
            )
        else:
            st.subheader("Restore a document")
            uploaded = st.file_uploader(
                "Upload anonymized PDF or DOCX", type=["pdf", "docx"], key="reverse_upload"
            )
            if uploaded:
                data, filename = uploaded.getvalue(), uploaded.name
            st.caption(
                "Use the original document reference, or leave it blank if none was entered. Keep the same vault and key."
            )
    if data is None:
        return
    context = sha256(data + (case + mode).encode()).hexdigest()
    if st.session_state.get("context") != context:
        for key in ("entities", "anonymized", "restored", "manual", "review"):
            st.session_state.pop(key, None)
        st.session_state.context = context
    source_digest = sha256(data + filename.encode()).hexdigest()
    if st.session_state.get("source_digest") != source_digest:
        with st.spinner("Reading document and running local OCR if needed…"):
            st.session_state.document = load_document(data, filename)
        st.session_state.source_digest = source_digest
    document = st.session_state.document
    for notice in document.notices:
        st.warning(notice)
    with st.expander("Original document preview"):
        preview(document.data, document.kind, document.text, "Source")
    if mode == "Anonymize":
        if "entities" not in st.session_state:
            with st.spinner("Detecting sensitive information locally…"):
                st.session_state.entities = detector().detect(document.text)
        entities = st.session_state.entities
        st.subheader("Review sensitive information")
        st.caption(
            "Detected with PII Shield. Uncheck false positives or change their type. "
            "A selected value replaces every exact occurrence."
        )
        rows = [
            {
                "Select": True,
                "Value": document.text[e.start : e.end],
                "Type": e.kind,
                "Confidence": round(e.score, 2),
                "Start": e.start,
                "End": e.end,
            }
            for e in entities
        ]
        edited = (
            st.data_editor(
                rows,
                key="review",
                hide_index=True,
                width="stretch",
                disabled=["Value", "Confidence", "Start", "End"],
                column_config={
                    "Type": st.column_config.SelectboxColumn(options=list(TYPES), required=True),
                    "Start": None,
                    "End": None,
                },
            )
            if rows
            else []
        )
        with st.expander("Add a missed value"):
            st.caption(
                "One exact value per line. Each value must occur within a single paragraph or PDF line."
            )
            manual_text = st.text_area("Manual values", key="manual")
            manual_type = st.selectbox("Manual entity type", TYPES)
        review_signature = repr((edited, manual_text, manual_type))
        if st.session_state.get("review_signature") != review_signature:
            st.session_state.pop("anonymized", None)
            st.session_state.pop("restored", None)
            st.session_state.review_signature = review_signature
        if st.button("Anonymize", type="primary"):
            selected = [
                Entity(int(r["Start"]), int(r["End"]), r["Type"]) for r in edited if r["Select"]
            ]
            manual = [(v.strip(), manual_type) for v in manual_text.splitlines() if v.strip()]
            st.session_state.pop("anonymized", None)
            st.session_state.pop("restored", None)
            with st.spinner("Anonymizing document and preparing your download…", show_time=True):
                st.session_state.anonymized = anonymize(document, selected, vault, case, manual)
        if "anonymized" in st.session_state:
            result = st.session_state.anonymized
            st.success(f"Anonymized {result.count} occurrences. Review the result before sharing.")
            preview(result.data, result.kind, result.text, "Anonymized preview")
            download(result, "Download anonymized document", "anonymized")
            if st.button("Reverse Anonymize", type="primary"):
                with st.spinner(
                    "Restoring original values and preparing your download…", show_time=True
                ):
                    st.session_state.restored = restore(
                        load_document(result.data, "file." + result.kind), vault, case
                    )
    else:
        if st.button("Reverse Anonymize", type="primary"):
            st.session_state.pop("restored", None)
            with st.spinner(
                "Restoring original values and preparing your download…", show_time=True
            ):
                st.session_state.restored = restore(document, vault, case)
    if "restored" in st.session_state:
        result = st.session_state.restored
        st.success(f"Restored {result.count} placeholder occurrences.")
        preview(result.data, result.kind, result.text, "Restored preview")
        download(result, "Download restored document", "restored")


try:
    main()
except AnonymizerError as error:
    st.error(str(error))
except Exception:
    # Do not send document contents, filenames or parser tracebacks to server logs/UI.
    st.error(
        "Processing failed safely. Check the installation and use a supported document structure."
    )
