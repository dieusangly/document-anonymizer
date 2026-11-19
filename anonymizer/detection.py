"""PII Shield detection with bilingual domain labels and review selections."""

import math
import re
from bisect import bisect_right
from dataclasses import dataclass

from .errors import AnonymizerError
from .pii_shield import Shield

TYPES = (
    "PERSON",
    "ADDRESS",
    "ORGANIZATION",
    "NRP",
    "TAX_ID",
    "INVOICE_NUMBER",
    "DATE_OF_BIRTH",
    "PHONE_NUMBER",
    "EMAIL_ADDRESS",
    "IBAN",
    "BIC",
    "ACCOUNT_NUMBER",
    "CUSTOMER_ID",
    "POLICY_NUMBER",
    "CLAIM_REFERENCE",
    "NATIONAL_ID",
    "HEALTH",
    "CREDIT_CARD",
    "OTHER",
    # Additional PII Shield 2.2.0 types, including extended NER labels.
    "DATE_TIME",
    "URL",
    "IP_ADDRESS",
    "ID_DOC",
    "CRYPTO",
    "MEDICAL_LICENSE",
    "US_SSN",
    "US_PASSPORT",
    "US_DRIVER_LICENSE",
    "UK_NHS",
    "UK_NIN",
    "UK_PASSPORT",
    "UK_CRN",
    "UK_DRIVING_LICENCE",
    "EU_VAT",
    "EU_PASSPORT",
    "DE_TAX_ID",
    "DE_SOCIAL_SECURITY",
    "FR_NIR",
    "FR_CNI",
    "IT_FISCAL_CODE",
    "IT_VAT",
    "ES_DNI",
    "ES_NIE",
    "CY_TIC",
    "CY_ID_CARD",
    "FI_HETU",
    "FI_BUSINESS_ID",
)
TYPE_ALIASES = {"LOCATION": "ADDRESS", "IBAN_CODE": "IBAN"}
TOKEN = re.compile(r"\[[A-Z][A-Z_]*_\d{3,}\]")
LABELS = {
    "PERSON": r"name|full name|client|customer|nom|titulaire|assuré|insured|beneficiary|bénéficiaire",
    "ADDRESS": r"address|adresse|residential address",
    "ORGANIZATION": r"company|organization|organisation|société|entreprise",
    "TAX_ID": r"tax id|tax number|vat|vat number|tva|numéro de tva",
    "INVOICE_NUMBER": r"invoice number|invoice no\.?|numéro de facture",
    "DATE_OF_BIRTH": r"date of birth|birth date|dob|date de naissance|né le|née le",
    "PHONE_NUMBER": r"phone|telephone|téléphone|mobile",
    "EMAIL_ADDRESS": r"email|e-mail|courriel",
    "IBAN": r"iban",
    "BIC": r"bic|swift",
    "ACCOUNT_NUMBER": r"account number|account no\.?|numéro de compte|compte",
    "CUSTOMER_ID": r"customer id|client id|identifiant client|référence client",
    "POLICY_NUMBER": r"policy number|policy no\.?|numéro de police|police|contrat",
    "CLAIM_REFERENCE": r"claim reference|claim number|référence sinistre|sinistre",
    "NATIONAL_ID": r"national id|national identification number|numéro national|nir|social security number",
    "HEALTH": r"health|medical information|diagnosis|diagnostic|santé|informations médicales",
}

_ADDRESS_BOUNDARIES = frozenset(
    (
        "account amount bic bill client compte conditions contact courriel credit customer "
        "date debit description details détails email facture iban invoice item livraison "
        "montant name nom notes paiement payment phone price prix quantity quantité "
        "reference référence résumé ship subtotal summary tax taxes telephone terms total "
        "tva téléphone vat"
    ).split()
)
_PLACE_CONNECTORS = frozenset("and d de des du en et l la le les of sous sur the upon".split())


@dataclass(frozen=True)
class Entity:
    start: int
    end: int
    kind: str
    score: float = 1.0


def _labelled_entities(text):
    for kind, labels in LABELS.items():
        for match in re.finditer(rf"(?im)^(?:{labels})\s*:\s*([^\n]+)", text):
            start, end = match.span(1)
            while end > start and text[end - 1].isspace():
                end -= 1
            if start < end and not TOKEN.search(text[start:end]):
                yield Entity(start, end, kind, 0.99)
    # GLiNER can miss names in short contact instructions despite sufficient
    # confidence on longer text. Keep this narrow English/French context rule.
    for match in re.finditer(
        r"(?i:\bcontact(?:er)?\s+)([A-ZÀ-ÖØ-Þ][\w’'-]+(?:[ \t]+[A-ZÀ-ÖØ-Þ][\w’'-]+){1,4})",
        text,
    ):
        yield Entity(*match.span(1), "PERSON", 0.95)


def _postal_entities(text):
    # Supplement GLiNER's incomplete multiline blocks with explicit street and
    # postal syntax, independent of invoice labels or a particular customer's data.
    patterns = (
        r"\d{1,6}[A-Za-z]?(?:[ \t]*[-–/][ \t]*\d{1,6})?[ \t]+"
        r"(?:[\w.'’\-]+[ \t]+){1,8}"
        r"(?:street|st\.?|road|rd\.?|avenue|ave\.?|lane|ln\.?|drive|dr\.?|way|close|court)\b[^\n]*",
        r"\d{1,6}(?:[ \t]*(?:bis|ter))?[, \t]+"
        r"(?:rue|avenue|boulevard|chemin|route|allée|allee|place|impasse|quai)[ \t]+[^\n]+",
        r"\d{5}[ \t]+[A-Za-zÀ-ÿ][^\n]+",
        r"[A-Za-zÀ-ÿ][\w .’'\-]+[ \t]+[A-Z]{1,2}\d[A-Z\d]?[ \t]*\d[A-Z]{2}",
        r"(?:[A-PR-WY]\d{2}|D6W)[ \t]?[0-9AC-FHKNPRTV-Y]{4}",
    )
    for pattern in patterns:
        for match in re.finditer(rf"(?im)^(?:{pattern})$", text):
            yield Entity(match.start(), match.end(), "ADDRESS", 0.95)


def _address_continuations(text, entities):
    """Fill short place-name lines after an address containing street/postal digits."""
    lines = list(re.finditer(r"(?m)^.*$", text))
    starts = [line.start() for line in lines]
    addresses = [e for e in entities if e.kind == "ADDRESS"]
    covered = {bisect_right(starts, e.start) - 1 for e in addresses}
    anchors = {
        bisect_right(starts, e.start) - 1
        for e in addresses
        if any(char.isdigit() for char in text[e.start : e.end])
    }
    for anchor in sorted(anchors):
        # Never promote new continuations to anchors: expansion stays bounded.
        for index in range(anchor + 1, min(anchor + 5, len(lines))):
            line = lines[index]
            value = line.group().strip()
            words = re.findall(r"[^\W\d_]+", value)
            if (
                not value
                or ":" in value
                or any(word.casefold() in _ADDRESS_BOUNDARIES for word in words)
            ):
                break
            # A second column can insert another street/postcode in reading order.
            if index in covered:
                continue
            if (
                len(value) > 64
                or not 1 <= len(words) <= 6
                or not value[0].isupper()
                or not all(char.isalpha() or char in " .’'-" for char in value)
                or not all(
                    word[0].isupper() or word.casefold() in _PLACE_CONNECTORS for word in words
                )
            ):
                break
            start = line.start() + len(line.group()) - len(line.group().lstrip())
            yield Entity(start, start + len(value), "ADDRESS", 0.85)


def _shield_entities(text, results):
    # JavaScript indexes UTF-16 code units; Python indexes Unicode code points.
    # Supplementary characters (e.g. emoji before a name) must not shift replacements.
    offsets = {0: 0}
    units = 0
    for index, char in enumerate(text):
        units += 2 if ord(char) > 0xFFFF else 1
        offsets[units] = index + 1
    try:
        for result in results:
            start, end = offsets[result["start"]], offsets[result["end"]]
            kind = TYPE_ALIASES.get(result["type"], result["type"])
            score = float(result["score"])
            if (
                not 0 <= start < end <= len(text)
                or kind not in TYPES
                or not math.isfinite(score)
                or not 0 <= score <= 1
                # PII Shield's organization rules collapse whitespace in the
                # reported text. Keep source offsets and exact source spelling.
                or " ".join(text[start:end].split()) != " ".join(result["text"].split())
            ):
                raise ValueError
            # Exports replace within a PDF line or Word paragraph. Keep every
            # line of a detected address block instead of discarding multiline spans.
            for match in re.finditer(r"[^\n]+", text[start:end]):
                value = match.group().strip()
                if value:
                    a = start + match.start() + len(match.group()) - len(match.group().lstrip())
                    yield Entity(a, a + len(value), kind, score)
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError):
        raise AnonymizerError(
            "PII Shield returned invalid entity spans. No scan was accepted."
        ) from None


class Detector:
    def __init__(self):
        self.shield = Shield()

    def detect(self, text):
        if not text.strip():
            return []
        automatic = list(_shield_entities(text, self.shield.detect(text)))
        # Explicit domain labels take priority over partial or differently typed
        # model predictions; all other detections use confidence and span length.
        candidates = (
            list(_labelled_entities(text))
            + list(_postal_entities(text))
            + sorted(automatic, key=lambda e: (-e.score, -(e.end - e.start), e.start))
        )
        candidates.extend(_address_continuations(text, candidates.copy()))
        chosen = []
        placeholders = [m.span() for m in TOKEN.finditer(text)]
        # Model predictions such as "IBAN" must not replace field labels or
        # collide with the type name inside generated [IBAN_001] placeholders.
        label_spans = [
            m.span() for m in re.finditer(rf"(?im)^(?:{'|'.join(LABELS.values())})\s*:", text)
        ]
        for entity in candidates:
            if any(
                entity.start < end and entity.end > start
                for start, end in placeholders + label_spans
            ):
                continue
            if not any(entity.start < old.end and entity.end > old.start for old in chosen):
                chosen.append(entity)
        # Once an identity is recognized, also find its exact repeated mentions.
        for entity in list(chosen):
            for match in re.finditer(re.escape(text[entity.start : entity.end]), text):
                if not any(match.start() < old.end and match.end() > old.start for old in chosen):
                    chosen.append(Entity(match.start(), match.end(), entity.kind, entity.score))
        return sorted(chosen, key=lambda e: e.start)


def selections(text, entities, manual=()):
    """Apply review choices to every exact occurrence, with deterministic overlap handling."""
    values = {}
    for value, kind in manual:
        if not value or kind not in TYPES or "\n" in value or TOKEN.search(value):
            raise AnonymizerError(
                "Manual values need a valid type and single-line non-placeholder text."
            )
        if value not in text:
            raise AnonymizerError("A manual value was not found in the document.")
        values[value] = kind
    for entity in entities:
        if not (0 <= entity.start < entity.end <= len(text)) or entity.kind not in TYPES:
            raise AnonymizerError("Invalid entity selection.")
        values.setdefault(text[entity.start : entity.end], entity.kind)
    # Longest values first, manual choices win for the same text.
    result = []
    for value, kind in sorted(values.items(), key=lambda item: -len(item[0])):
        for match in re.finditer(re.escape(value), text):
            if not any(match.start() < e.end and match.end() > e.start for e in result):
                result.append(Entity(match.start(), match.end(), kind))
    return sorted(result, key=lambda e: e.start)
