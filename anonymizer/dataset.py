"""Deterministic fictional fixtures and independently declared entity annotations."""

import json
import re
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from .documents import load_document

SAMPLES = [
    {
        "filename": "bank_statement_fr.pdf",
        "language": "fr",
        "title": "Relevé bancaire fictif",
        "intro": "Banque Démonstration - Relevé du 1 au 31 octobre 2026",
        "fields": [
            ("Titulaire", "Camille Moreau", "PERSON"),
            ("Adresse", "18 rue des Lilas, 69003 Lyon", "ADDRESS"),
            ("Date de naissance", "14/03/1988", "DATE_OF_BIRTH"),
            ("Téléphone", "+33 6 12 34 56 78", "PHONE_NUMBER"),
            ("Courriel", "camille.moreau@example.com", "EMAIL_ADDRESS"),
            ("IBAN", "FR76 3000 6000 0112 3456 7890 189", "IBAN"),
            ("BIC", "AGRIFRPPXXX", "BIC"),
            ("Numéro de compte", "000123456789", "ACCOUNT_NUMBER"),
            ("Identifiant client", "CLI-2026-0042", "CUSTOMER_ID"),
        ],
        "rows": [
            ("02/10/2026", "Virement salaire", "+2 850,00 EUR"),
            ("15/10/2026", "Prélèvement assurance", "-42,00 EUR"),
        ],
        "closing": "Ce relevé est destiné à Camille Moreau. Solde final : 4 328,50 EUR.",
    },
    {
        "filename": "onboarding_en.docx",
        "language": "en",
        "title": "Bank client onboarding",
        "intro": "Demonstration Bank records the following fictional customer details.",
        "fields": [
            ("Full name", "Daniel Harper", "PERSON"),
            ("Address", "42 Willow Lane, Bristol BS1 4QA", "ADDRESS"),
            ("Date of birth", "22/07/1991", "DATE_OF_BIRTH"),
            ("Phone", "+44 7700 900123", "PHONE_NUMBER"),
            ("Email", "daniel.harper@example.org", "EMAIL_ADDRESS"),
            ("IBAN", "GB82 WEST 1234 5698 7654 32", "IBAN"),
            ("BIC", "DABAGB2LXXX", "BIC"),
            ("Account number", "98765432", "ACCOUNT_NUMBER"),
            ("Customer ID", "CUS-2026-0108", "CUSTOMER_ID"),
            ("National ID", "QQ123456C", "NATIONAL_ID"),
        ],
        "rows": [("Identity check", "Complete"), ("Account purpose", "Salary and savings")],
        "closing": "Daniel Harper confirms that these details are correct.",
    },
    {
        "filename": "insurance_claim_fr.pdf",
        "language": "fr",
        "title": "Déclaration de sinistre",
        "intro": "Assurance Démonstration - Dossier fictif ouvert le 5 novembre 2026",
        "fields": [
            ("Assuré", "Camille Moreau", "PERSON"),
            ("Adresse", "18 rue des Lilas, 69003 Lyon", "ADDRESS"),
            ("Courriel", "camille.moreau@example.com", "EMAIL_ADDRESS"),
            ("Police", "POL-FR-2026-0087", "POLICY_NUMBER"),
            ("Référence sinistre", "SIN-2026-0912", "CLAIM_REFERENCE"),
            ("Bénéficiaire", "Lucie Moreau", "PERSON"),
            ("NIR", "2 88 03 69 123 456 78", "NATIONAL_ID"),
            ("Diagnostic", "fracture du poignet gauche", "HEALTH"),
            ("IBAN", "FR76 3000 6000 0112 3456 7890 189", "IBAN"),
        ],
        "rows": [("Consultation", "85,00 EUR"), ("Radiographie", "120,00 EUR")],
        "closing": "Camille Moreau demande le remboursement des frais médicaux.",
    },
    {
        "filename": "insurance_contract_mixed.docx",
        "language": "fr/en",
        "title": "Contrat assurance vie Life insurance",
        "intro": "Assurance Démonstration - Conditions contractuelles pour un dossier fictif.",
        "fields": [
            ("Titulaire", "Camille Moreau", "PERSON"),
            ("Address", "18 rue des Lilas, 69003 Lyon", "ADDRESS"),
            ("Date of birth", "14/03/1988", "DATE_OF_BIRTH"),
            ("Policy number", "POL-FR-2026-0087", "POLICY_NUMBER"),
            ("Customer ID", "CLI-2026-0042", "CUSTOMER_ID"),
            ("Beneficiary", "Daniel Harper", "PERSON"),
            ("Email", "daniel.harper@example.org", "EMAIL_ADDRESS"),
            ("Health", "asthme chronique / chronic asthma", "HEALTH"),
            ("IBAN", "FR76 3000 6000 0112 3456 7890 189", "IBAN"),
        ],
        "rows": [
            ("Capital garanti / Benefit", "100 000 EUR"),
            ("Prime / Premium", "42 EUR / month"),
        ],
        "closing": "Camille Moreau désigne Daniel Harper comme bénéficiaire.",
    },
]


def _pdf(path, sample):
    pdf = canvas.Canvas(str(path), pagesize=A4, invariant=1)
    pdf.setTitle(sample["title"])
    pdf.setAuthor(
        sample["fields"][0][1]
    )  # Metadata is intentionally sensitive to exercise sanitization.
    pdf.setFont("Helvetica-Bold", 19)
    pdf.drawString(48, 786, sample["title"])
    pdf.setFont("Helvetica", 10)
    pdf.drawString(48, 758, sample["intro"])
    y = 718
    for label, value, _ in sample["fields"]:
        pdf.drawString(48, y, f"{label}: {value}")
        y -= 27
    y -= 20
    pdf.line(48, y + 16, 547, y + 16)
    for row in sample["rows"]:
        for x, value in zip((48, 210, 420) if len(row) == 3 else (48, 350), row):
            pdf.drawString(x, y, value)
        y -= 25
    pdf.drawString(48, y - 30, sample["closing"])
    pdf.setFont("Helvetica", 8)
    pdf.drawString(48, 40, "Fictional demonstration data - Not a real financial document")
    pdf.save()


def _docx(path, sample):
    doc = Document()
    section = doc.sections[0]
    section.top_margin = section.bottom_margin = Inches(0.7)
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10)
    normal.paragraph_format.space_after = Pt(7)
    for name in ("Title", "Heading 1"):
        doc.styles[name].font.color.rgb = RGBColor(0, 0, 0)
        for border in doc.styles[name].element.iter(qn("w:pBdr")):
            border.getparent().remove(border)
    doc.add_paragraph(sample["title"], "Title")
    doc.add_paragraph(sample["intro"])
    doc.add_paragraph("Client details", "Heading 1")
    for label, value, _ in sample["fields"]:
        paragraph = doc.add_paragraph()
        paragraph.add_run(label + ": ").bold = True
        # Split identities across runs to test actual Word editing behavior.
        midpoint = len(value) // 2
        paragraph.add_run(value[:midpoint])
        paragraph.add_run(value[midpoint:]).italic = True
    table = doc.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    for row in sample["rows"]:
        cells = table.add_row().cells
        for cell, value in zip(cells, row):
            cell.text = value
    doc.add_paragraph(sample["closing"])
    section.header.paragraphs[0].text = "Customer: " + sample["fields"][0][1]
    section.footer.paragraphs[0].text = "Fictional demonstration data - Not a real contract"
    doc.core_properties.author = sample["fields"][0][1]
    doc.save(path)


def generate(directory="data/synthetic"):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    manifest = []
    for sample in SAMPLES:
        path = directory / sample["filename"]
        (_pdf if path.suffix == ".pdf" else _docx)(path, sample)
        text = load_document(path.read_bytes(), path.name).text
        expected = []
        for _, value, kind in sample["fields"]:
            for match in re.finditer(re.escape(value), text):
                expected.append(
                    {"start": match.start(), "end": match.end(), "kind": kind, "value": value}
                )
        manifest.append(
            {
                "filename": path.name,
                "language": sample["language"],
                "title": sample["title"],
                "entities": sorted(expected, key=lambda e: e["start"]),
            }
        )
    (directory / "annotations.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


if __name__ == "__main__":
    generate()
    print("Generated four fictional documents and annotations in data/synthetic/.")
