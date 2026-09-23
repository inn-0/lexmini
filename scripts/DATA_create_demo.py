# scripts/DATA_create_demo.py
"""Create the synthetic review fixture, with no real client or personal data.

Rationale: exercise PDF positions, repeated mentions, legal terms and metadata.
Assumptions: PyMuPDF is installed in this project's virtual environment.
Constraints: keep TEST_ naming and mark every page as synthetic.
"""

from pathlib import Path as pPath

import pymupdf

root = pPath(__file__).resolve().parents[1]
with pymupdf.open() as doc:
  page = doc.new_page()
  page.insert_text((50, 45), "SYNTHETIC EXAMPLE / NO REAL CLIENT DATA", fontsize=9, color=(.3,.4,.3))
  page.insert_text((50, 93), "Translation instructions", fontsize=24, fontname="tiro")
  page.insert_text((50, 125), "Service agreement - confidential draft", fontsize=12)
  page.insert_textbox(pymupdf.Rect(50, 160, 540, 740), "\n".join([
    "Client: Alpen Example AG", "Counterparty: Lake Example GmbH", "",
    "Contact: Alice Example", "Email: alice@example.com", "Phone: +41 79 555 01 23", "",
    "The agreement starts on 2026-10-01. Payment is CHF 12,500.", "",
    "The litigation strategy is to seek a negotiated settlement.",
    "Trade secret: the draft describes the unreleased Example process.", "",
    "Send the translation to alice@example.com.", "",
    "Keep the obligations and payment schedule understandable.",
    "Replace the parties and personal contact information before sharing.",
  ]), fontsize=12, lineheight=1.7)
  page = doc.new_page()
  page.insert_text((50, 45), "SYNTHETIC EXAMPLE / NO REAL CLIENT DATA", fontsize=9, color=(.3,.4,.3))
  page.insert_text((50, 93), "Deutsche Vertragsnotiz", fontsize=24, fontname="tiro")
  page.insert_textbox(pymupdf.Rect(50, 150, 540, 740), "\n".join([
    "Mandantin: Alpen Example AG", "Kontakt: Anna Muster", "E-Mail: anna@example.com", "",
    "Der Vertrag beginnt am 01.10.2026. Die Zahlung beträgt CHF 12,500.", "",
    "Prozessstrategie: Wir besprechen zuerst einen Vergleich.",
    "Geschäftsgeheimnis: Das Verfahren ist noch nicht veröffentlicht.", "",
    "Bitte Namen entfernen und Zahlungsbedingungen verständlich behalten.",
  ]), fontsize=12, lineheight=1.7)
  doc.set_metadata({"author": "Synthetic Author", "subject": "Synthetic private matter"})
  doc.save(root / "data/TEST_legal_demo.pdf")
print("Created data/TEST_legal_demo.pdf")
