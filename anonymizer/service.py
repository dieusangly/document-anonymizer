"""Review, replacement and restoration orchestration."""

import re
from dataclasses import dataclass

from .detection import TOKEN, TYPES, selections
from .documents import export_document, load_document
from .errors import AnonymizerError, MappingError


@dataclass
class Result:
    data: bytes
    text: str
    kind: str
    count: int


def transformer(replacements):
    pattern = (
        re.compile("|".join(re.escape(v) for v in sorted(replacements, key=len, reverse=True)))
        if replacements
        else None
    )

    def transform(text):
        cursor = 0
        chunks = []
        for match in pattern.finditer(text) if pattern else []:
            if cursor < match.start():
                chunks.append((cursor, match.start(), None))
            chunks.append((match.start(), match.end(), replacements[match.group()]))
            cursor = match.end()
        if cursor < len(text):
            chunks.append((cursor, len(text), None))
        return chunks

    return transform


def anonymize(document, entities, vault, case, manual=()):
    if TOKEN.search(document.text) or document.marker:
        raise AnonymizerError(
            "This document already contains placeholders. Restore it before anonymizing again."
        )
    chosen = selections(document.text, entities, manual)
    if not chosen:
        raise AnonymizerError("Select at least one entity or add a manual value.")
    values = [(document.text[e.start : e.end], e.kind) for e in chosen]
    mappings = vault.assign(case, values)
    inverse = {v: k for k, v in mappings["mapping"].items()}
    replacements = {value: inverse[value] for value, _ in values}
    data = export_document(document, transformer(replacements), mappings["id"])
    output = load_document(data, "output." + document.kind)
    if any(value in output.text for value in replacements):
        raise AnonymizerError(
            "Export validation failed: a selected value remains. No output was released."
        )
    return Result(data, output.text, document.kind, len(chosen))


def restore(document, vault, case):
    stored = vault.get(case)
    if document.marker and document.marker != stored["id"]:
        raise MappingError("This document belongs to another case. Select its original case.")
    mapping = stored["mapping"]
    # Include unknown types and malformed known placeholders; do not silently partly restore.
    suspect = re.compile(
        r"\[[A-Z][A-Z_]*[_ -][^\]\n]*\]|\[(?:" + "|".join(TYPES) + r")_\d+\b(?!\])"
    )
    found = {m.group() for m in suspect.finditer(document.text)}
    if not found:
        raise MappingError("No placeholders found. Upload an anonymized PDF or DOCX.")
    missing = found - mapping.keys()
    if missing:
        raise MappingError(
            f"Missing or malformed mappings for {len(missing)} placeholder(s). Nothing was restored."
        )
    data = export_document(document, transformer({t: mapping[t] for t in found}))
    output = load_document(data, "output." + document.kind)
    return Result(data, output.text, document.kind, sum(document.text.count(t) for t in found))
