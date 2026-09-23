# tests/test_paragraphs.py
"""Protect paragraph context and source positions at PDF line/column boundaries."""
import json
import unittest
from pathlib import Path as pPath
import pymupdf
from lexmini import paragraphs, pdf, rules, services
from lexmini.layout import LayoutRegion
from lexmini.schemas import Context, RestoreReviewRequest


class ParagraphTests(unittest.TestCase):
  def test_wrapped_entity_maps_back_to_both_lines(self):
    with pymupdf.open() as document:
      page = document.new_page()
      page.insert_text((50,60), 'Alice')
      page.insert_text((50,75), 'Example')
      page.insert_text((350,60), 'Unrelated column')
      source = pdf.extract(document.tobytes()).pages[0]
    region = LayoutRegion(page_number=1,label='text',box=(45,40,160,80))
    units = paragraphs.build(source,[region])
    unit = next(p for p in units if p.source == 'docling')
    self.assertEqual(unit.text, 'Alice Example')
    def detector(texts, languages):
      return [[dict(start=0,end=len(text),field_type='person_name',reason='test')]
        if text == 'Alice Example' else [] for text in texts]
    spans = paragraphs.detect([source],[region],['en'],detector)[0]
    recovered = ''.join(source.text[s['start']:s['end']] for s in spans)
    self.assertIn('Alice', recovered)
    self.assertIn('Example', recovered)
    self.assertNotIn('Unrelated', recovered)
    self.assertTrue(all(source.boxes[i] for s in spans for i in range(s['start'],s['end']) if not source.text[i].isspace()))

  def test_public_medical_sentence_covers_wrapped_depression_and_medication(self):
    root = pPath(__file__).resolve().parents[1]
    name = 'CH_BVGE_001_E-1088-2022_2022-11-07'
    baseline = json.loads((root / f'data/quality/{name}.baseline.json').read_text())
    saved = json.loads((root / f'data/quality/{name}.screening.json').read_text())
    pages = pdf.extract((root / baseline['pdf_path']).read_bytes()).pages
    page = pages[4]
    regions = [LayoutRegion.model_validate(r) for r in saved['regions']]
    findings = rules.findings_for_page('regression',page,[],Context(),saved['spacy_spans'][4],regions)
    medical = [f for f in findings if f.field_type == 'medical_information']
    phrase = next(f for f in medical if 'diagnostic' in f.original_text)
    for term in ['dépressif léger','Relaxane','Redormin','Quétiapine']:
      self.assertIn(term, ' '.join(phrase.original_text.split()))
    self.assertGreater(len(phrase.location.boxes),1)
    self.assertIn('docling paragraph',phrase.reason)
    self.assertFalse(any(f.field_type == 'address' and f.original_text.strip() in {'Relaxane','Redormin','Quétiapine'} for f in findings))


class RecoveryTests(unittest.TestCase):
  def tearDown(self):
    services.store.sessions.clear()

  def test_restore_preserves_selection_and_recomputes_coordinates(self):
    with pymupdf.open() as document:
      document.new_page().insert_text((50,60),'Email alice@example.com')
      payload = document.tobytes()
    first=services.store.create(payload,'recovery.pdf')
    page=services.store.get(first.document_id).extracted.pages[0]
    findings=rules.findings_for_page(first.document_id,page,[],Context())
    findings[0].selected=False
    findings[0].location.boxes=[(0,0,1,1)]
    services.store.remove(first.document_id)
    second=services.store.create(payload,'recovery.pdf')
    recovered=services.restore_review(second.document_id,RestoreReviewRequest(findings=findings,context=Context()))
    self.assertFalse(recovered.findings[0].selected)
    self.assertNotEqual(recovered.findings[0].location.boxes,[(0,0,1,1)])
    self.assertEqual(recovered.findings[0].original_text,'alice@example.com')
    third=services.store.create(payload,'recovery.pdf')
    findings[0].original_text='not in the file'
    with self.assertRaisesRegex(ValueError,'does not match'):
      services.restore_review(third.document_id,RestoreReviewRequest(findings=findings,context=Context()))


if __name__ == '__main__':
  unittest.main()
