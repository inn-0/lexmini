# tests/test_review.py
"""Verify selected occurrence removal, PDF rebuilding, offsets and API failure handling."""

import time
import hashlib
import tempfile
import unittest
from pathlib import Path as pPath
from unittest.mock import patch

import pymupdf
from fastapi.testclient import TestClient

from lexmini import pdf, rules, services
from lexmini.main import app
from lexmini.schemas import Context, ExportRequest
from lexmini.tokens import TokenRegistry, replace_pages
from lexmini.screening_memory import ScreeningMemory


def fixture(rotation=0):
  with pymupdf.open() as doc:
    page = doc.new_page()
    page.insert_text((50, 100), "alice@example.com")
    page.insert_text((50, 180), "alice@example.com")
    page.insert_text((50, 250), "Client: Example AG. Payment CHF 12,500 on 2026-10-01.")
    page.set_rotation(rotation)
    doc.set_metadata({"author": "Private author"})
    doc.embfile_add("private.txt", b"hidden private data")
    return doc.tobytes()


def empty_screen(texts, languages, payload):
  return {"spacy_spans": [[] for _ in texts], "regions": [],
    "text_hashes": [hashlib.sha256(t.encode()).hexdigest() for t in texts],
    "pdf_sha256": hashlib.sha256(payload).hexdigest() if payload else None, "engine": "synthetic-test"}


class ReviewTests(unittest.TestCase):
  def setUp(self):
    self.memory_directory = tempfile.TemporaryDirectory()
    self.memory_patch = patch('lexmini.services.memory', ScreeningMemory(pPath(self.memory_directory.name) / 'memory.json'))
    self.memory_patch.start()

  def tearDown(self):
    services.store.sessions.clear()
    self.memory_patch.stop()
    self.memory_directory.cleanup()

  def test_selected_occurrence_and_rotated_pdf(self):
    for rotation in (0, 90):
      payload = fixture(rotation)
      pages = pdf.extract(payload).pages
      text = pages[0].text
      start = text.rfind("alice@example.com")
      spans = [{"start": start, "end": start + 17, "text": "alice@example.com", "label": "private_email"}]
      findings = rules.findings_for_page("doc", pages[0], spans, Context())
      chosen = [f for f in findings if f.field_type == "email" and f.location.start == start]
      self.assertEqual(len(chosen), 1)
      self.assertEqual(pdf.export_text(pages, chosen).count("alice@example.com"), 1)
      self.assertGreater(chosen[0].location.boxes[0][1], 150)
      clean = pdf.export_pdf(payload, chosen)
      with pymupdf.open(stream=clean, filetype="pdf") as result:
        self.assertEqual(result[0].get_text().strip(), "Contact")
        self.assertFalse(result.metadata.get("author"))
        self.assertEqual(result.embfile_count(), 0)
        x0,y0,x1,y1 = chosen[0].location.boxes[0]
        pix = result[0].get_pixmap()
        colour = pix.pixel(int((x0+x1)/2), int((y0+y1)/2))
        self.assertEqual(colour[:3], (86, 180, 233))

  def test_ordinary_dates_default_to_keep_and_amounts_need_review(self):
    page = pdf.extract(fixture()).pages[0]
    findings = rules.findings_for_page("doc", page, [], Context(goal="Keep dates and amounts"))
    relevant = [f for f in findings if f.field_type in {"date", "amount"}]
    self.assertEqual(len(relevant), 2)
    self.assertTrue(all(f.context_suggestion == "keep" for f in relevant))
    self.assertFalse(next(f for f in relevant if f.field_type=="date").selected)
    self.assertTrue(next(f for f in relevant if f.field_type=="amount").selected)
    self.assertTrue(all(f.detection_confidence is None for f in findings))

  def test_tokens_stable_private_and_optional_x(self):
    # Token-format assertions use fixed detections; real spaCy has separate tests.
    detector_patch = patch("lexmini.services.spacy_detector.detect", return_value=[[]])
    detector_patch.start()
    self.addCleanup(detector_patch.stop)
    review = services.store.create(fixture(), "test.pdf")
    context = Context(confidential_terms=["alice@example.com"])
    with patch("lexmini.services.screen_remote", side_effect=empty_screen):
      first = services.analyse(review.document_id, context)
    emails = [f for f in first.findings if f.original_text == "alice@example.com" and f.field_type == "confidential_term"]
    self.assertEqual(len(emails), 2)
    self.assertEqual(emails[0].replacement, "[TERM_00001]")
    self.assertEqual(emails[0].replacement, emails[1].replacement)
    self.assertTrue(any(f.replacement == "[PARTY_00001]" for f in first.findings))
    self.assertTrue(any(f.replacement == "[DATE_00001]" for f in first.findings))
    args = dict(selected_ids=[f.finding_id for f in first.findings], revision=1)
    text = services.export(review.document_id, ExportRequest(**args, format="text")).decode()
    self.assertEqual(text.count("[TERM_00001]"), 2)
    self.assertNotIn("alice@example.com", text)
    hidden = services.export(review.document_id, ExportRequest(**args, format="text", replacement_style="x")).decode()
    self.assertIn("[X]", hidden)
    self.assertNotIn("[TERM_", hidden)
    payload = services.export(review.document_id, ExportRequest(**args, format="pdf"))
    with pymupdf.open(stream=payload, filetype="pdf") as doc:
      content = "".join(p.get_text() for p in doc)
      self.assertIn("[TERM_00001]", content)
      self.assertNotIn("alice@example.com", content)
      self.assertEqual(doc.embfile_count(), 0)
      self.assertFalse(doc.metadata.get("author"))
    session = services.store.get(review.document_id)
    self.assertEqual(session.tokens.values["[TERM_00001]"]["original_text"], "alice@example.com")
    with patch("lexmini.services.screen_remote", side_effect=empty_screen):
      second = services.analyse(review.document_id, context)
    self.assertEqual([f.replacement for f in first.findings], [f.replacement for f in second.findings])

  def test_overlapping_token_mapping_covers_full_removed_value(self):
    page = pdf.extract(fixture()).pages[0]
    context = Context(confidential_terms=["alice@example", "example.com"])
    findings = [f for f in rules.findings_for_page("doc", page, [], context) if f.field_type == "confidential_term"]
    registry = TokenRegistry()
    text = replace_pages([page], findings, registry, "tokens")[0]
    self.assertNotIn("alice@", text)
    self.assertNotIn("example.com", text)
    self.assertEqual(registry.values["[TEXT_00001]"]["original_text"], "alice@example.com")

  def test_bad_model_offsets_rejected(self):
    page = pdf.extract(fixture()).pages[0]
    with self.assertRaises(ValueError):
      rules.findings_for_page("doc", page, [{"start": 0, "end": 5, "text": "wrong", "label": "private_person"}], Context())

  def test_partial_model_date_merges_with_full_rule(self):
    with pymupdf.open() as doc:
      doc.new_page().insert_text((50,100), "Decision du 27 mai 2021. Audience le 27 mai 2021.")
      page = pdf.extract(doc.tobytes()).pages[0]
    start = page.text.index("27 mai")
    findings = rules.findings_for_page("doc", page,
      [{"start":start,"end":start+6,"text":"27 mai","label":"private_date"}], Context())
    dates = [f for f in findings if f.field_type == "date"]
    self.assertEqual(len(dates),2)
    self.assertEqual(dates[0].original_text,"27 mai 2021")
    self.assertEqual(dates[0].entity_id,dates[1].entity_id)
    self.assertIn("date-rule",dates[0].detector)
    self.assertIn("openai/privacy-filter",dates[0].detector)
    self.assertIn("personal-private",dates[0].sensitivity_levels)
    self.assertIn("professional-secrecy",dates[0].sensitivity_levels)
    self.assertIn("Decision",dates[0].excerpt_before)

  def test_overlapping_spans_do_not_leak(self):
    page = pdf.extract(fixture()).pages[0]
    ctx = Context(confidential_terms=["alice@example.com", "example.com"])
    findings = rules.findings_for_page("doc", page, [], ctx)
    text = pdf.export_text([page], [f for f in findings if f.field_type == "confidential_term"])
    self.assertNotIn("alice@", text)
    self.assertNotIn("example.com", text)

  def test_expired_and_unreadable_documents(self):
    review = services.store.create(fixture(), "test.pdf")
    services.store.sessions[review.document_id].expires = time.monotonic() - 1
    with self.assertRaises(KeyError):
      services.store.get(review.document_id)
    with pymupdf.open() as doc:
      doc.new_page()
      review = services.store.create(doc.tobytes(), "scan.pdf")
    self.assertFalse(review.pages[0].readable)
    services.store.get(review.document_id).review.analysed = True
    with self.assertRaisesRegex(ValueError, "unreadable"):
      services.export(review.document_id, ExportRequest(selected_ids=[], revision=0, format="pdf"))

  def test_api_selection_and_model_failure(self):
    with TestClient(app) as client:
      self.assertEqual(client.get("/health").status_code, 200)
      self.assertEqual(client.post("/api/documents", content=fixture()).status_code, 403)
      headers = {"X-Lexmini-Client": "review", "Content-Type": "application/pdf"}
      response = client.post("/api/documents?filename=test.pdf", headers=headers, content=fixture())
      self.assertEqual(response.status_code, 200)
      key = response.json()["document_id"]
      route = f"/api/documents/{key}"
      headers = {"X-Lexmini-Client": "review"}
      with patch("lexmini.services.screen_remote", side_effect=RuntimeError("synthetic error")):
        self.assertEqual(client.post(route + "/analyse", headers=headers, json={}).status_code, 503)
      self.assertFalse(client.get(route).json()["analysed"])
      with patch("lexmini.services.screen_remote", side_effect=empty_screen):
        analysed = client.post(route + "/analyse", headers=headers, json={}).json()
      selection = {"selected_ids": [f["finding_id"] for f in analysed["findings"]], "revision": 1, "format": "text"}
      result = client.post(route + "/export", headers=headers, json=selection)
      self.assertEqual(result.status_code, 200)
      self.assertNotIn("CHF 12,500", result.text)
      selection["selected_ids"] = ["invented"]
      self.assertEqual(client.post(route + "/export", headers=headers, json=selection).status_code, 400)
      selection.update(selected_ids=[], revision=0)
      self.assertEqual(client.post(route + "/export", headers=headers, json=selection).status_code, 400)
      client.delete(route, headers=headers)
      self.assertEqual(client.get(route).status_code, 404)


if __name__ == "__main__":
  unittest.main()
