"""Presidio recognizers plus bilingual domain labels; no runtime downloads."""

import re
from dataclasses import dataclass

import spacy
import tldextract
from presidio_analyzer import AnalyzerEngine, EntityRecognizer, RecognizerResult
from presidio_analyzer.nlp_engine import SpacyNlpEngine
from presidio_analyzer.predefined_recognizers import EmailRecognizer

from .errors import AnonymizerError

TYPES = (
    "PERSON",
    "ADDRESS",
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
)
TOKEN = re.compile(r"\[[A-Z][A-Z_]*_\d{3,}\]")
LABELS = {
    "PERSON": r"name|full name|client|customer|nom|titulaire|assuré|insured|beneficiary|bénéficiaire",
    "ADDRESS": r"address|adresse|residential address",
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


@dataclass(frozen=True)
class Entity:
    start: int
    end: int
    kind: str
    score: float = 1.0


class DomainRecognizer(EntityRecognizer):
    def __init__(self, language):
        super().__init__(supported_entities=list(LABELS), supported_language=language)

    def load(self):
        pass

    def analyze(self, text, entities, nlp_artifacts=None):
        results = []
        for kind, labels in LABELS.items():
            pattern = rf"(?im)^(?:{labels})\s*:\s*([^\n]+)"
            for match in re.finditer(pattern, text):
                start, end = match.span(1)
                while end > start and text[end - 1].isspace():
                    end -= 1
                if not TOKEN.search(text[start:end]):
                    results.append(RecognizerResult(kind, start, end, 0.99))
        return results


class LocalEmailRecognizer(EmailRecognizer):
    extractor = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)

    def validate_result(self, pattern_text):
        return self.extractor(pattern_text).fqdn != ""


class Detector:
    def __init__(self):
        models = [
            {"lang_code": "en", "model_name": "en_core_web_sm"},
            {"lang_code": "fr", "model_name": "fr_core_news_sm"},
        ]
        # Presidio otherwise attempts to install absent spaCy models automatically.
        if any(not spacy.util.is_package(model["model_name"]) for model in models):
            raise AnonymizerError(
                "Local language models are missing. Install requirements.txt first."
            )
        nlp = SpacyNlpEngine(models=models)
        nlp.load()
        self.engine = AnalyzerEngine(nlp_engine=nlp, supported_languages=["en", "fr"])
        # Disable tldextract's public-suffix network refresh, including on first use.
        self.engine.registry.recognizers = [
            r for r in self.engine.registry.recognizers if not isinstance(r, EmailRecognizer)
        ]
        for language in ("en", "fr"):
            self.engine.registry.add_recognizer(LocalEmailRecognizer(supported_language=language))
            self.engine.registry.add_recognizer(DomainRecognizer(language))

    def detect(self, text):
        candidates = []
        for language in ("en", "fr"):
            results = self.engine.analyze(
                text=text,
                language=language,
                entities=list(LABELS) + ["IBAN_CODE", "CREDIT_CARD"],
                score_threshold=0.5,
            )
            candidates.extend(
                Entity(
                    r.start,
                    r.end,
                    "IBAN" if r.entity_type == "IBAN_CODE" else r.entity_type,
                    r.score,
                )
                for r in results
            )
        # Labelled values take priority; larger spans prevent partial name/address masking.
        chosen = []
        placeholders = [m.span() for m in TOKEN.finditer(text)]
        for entity in sorted(candidates, key=lambda e: (-e.score, -(e.end - e.start), e.start)):
            value = text[entity.start : entity.end]
            if "\n" in value or (
                entity.kind == "PERSON" and entity.score < 0.99 and len(value.split()) < 2
            ):
                continue
            if any(entity.start < end and entity.end > start for start, end in placeholders):
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
