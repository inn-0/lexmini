# tests/test_layout_and_governance.py
"""Verify layout decisions, exact source selection and organisation isolation.

Only synthetic temporary memory is used. No production terms or model calls.
"""

import json
import tempfile
import unittest
from pathlib import Path as pPath
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from lexmini import layout, pdf, rules, services
from lexmini.main import app
from lexmini.schemas import Context, LearnRequest
from lexmini.screening_memory import ScreeningMemory
from test_screening_memory import document


class GovernanceTests(unittest.TestCase):
  def tearDown(self):
    services.store.sessions.clear()

  def test_only_approved_terms_and_matching_organisation(self):
    with tempfile.TemporaryDirectory() as directory:
      path = pPath(directory) / 'memory.json'
      memory = ScreeningMemory(path)
      common = dict(text='Project Evergreen',field_type='confidential_term',sensitivity_levels=['professional-secrecy'],review_set='*',origin_document_hash='synthetic')
      memory.remember(**common,organisation_id='org-a')
      self.assertEqual(len(memory.for_screening('matter',organisation_id='org-a')),1)
      self.assertEqual(memory.for_screening('matter',organisation_id='org-b'),[])
      with self.assertRaisesRegex(ValueError,'approved'):
        memory.remember(**common,organisation_id='org-b',approval_state='candidate')
      data = json.loads(path.read_text())
      data['terms'][0]['approval_state'] = 'candidate'
      path.write_text(json.dumps(data))
      self.assertEqual(memory.for_screening('matter',organisation_id='org-a'),[])

  def test_default_manual_annotation_is_not_saved_and_org_cannot_be_supplied(self):
    self.assertFalse(LearnRequest(revision=1,text='Project Evergreen').remember)
    for model, values in [(Context, {}),(LearnRequest,dict(revision=1,text='Project Evergreen'))]:
      with self.assertRaises(ValidationError):
        model(**values,organisation_id='somebody-else')

  def test_document_pins_server_organisation_and_saves_into_it(self):
    with tempfile.TemporaryDirectory() as directory:
      memory = ScreeningMemory(pPath(directory) / 'memory.json')
      with patch('lexmini.services.memory',memory), patch('lexmini._config.ORGANISATION_ID','org-a'):
        review = services.store.create(document('Project Evergreen.'),'synthetic.pdf')
        services.apply_predictions(review.document_id,Context(),[[]])
        services.learn(review.document_id,LearnRequest(revision=1,text='Project Evergreen',field_type='organisation_name',remember=True,workspace_wide=True))
      self.assertEqual(len(memory.for_screening('another-matter',organisation_id='org-a')),1)
      self.assertEqual(memory.for_screening('another-matter',organisation_id='org-b'),[])
      self.assertEqual(services.store.get(review.document_id).organisation_id,'org-a')

  def test_page_text_preserves_characters_and_boxes(self):
    review = services.store.create(document('Secretariat Etat SEM.'),'synthetic.pdf')
    with TestClient(app) as client:
      response = client.get(f'/api/documents/{review.document_id}/pages/1/text')
      self.assertEqual(response.status_code,200)
      self.assertEqual(len(response.json()['text']),len(response.json()['boxes']))
      self.assertIn('Secretariat Etat SEM.',response.json()['text'])
      self.assertEqual(client.get(f'/api/documents/{review.document_id}/pages/2/text').status_code,400)

  def test_marker_is_kept_but_heading_name_is_not_exempt(self):
    for text, expected_selected in [('L.',False),('Alice Example',True)]:
      page = pdf.extract(document(text)).pages[0]
      spans = [dict(start=0,end=len(text),field_type='person_name',level='personal-private',subcategory='named_entity',detector='spacy/test',reason='Synthetic')]
      findings = rules.findings_for_page('doc',page,[],Context(),spans)
      region = layout.LayoutRegion(page_number=1,label='section_header',box=(0,0,600,800),text=text)
      layout.annotate(findings,[page],[region])
      self.assertEqual(findings[0].selected,expected_selected)
      self.assertEqual(findings[0].review_signal,'weak')
      self.assertIsNone(findings[0].detection_confidence)

  def test_approved_marker_overrides_layout_and_generic_word_is_flagged(self):
    page = pdf.extract(document('Etat')).pages[0]
    for source, expected in [('spacy/test','weak'),('screening-memory','approved'),('screening-memory-fuzzy','weak')]:
      extra = [dict(start=0,end=4,field_type='person_name',level='personal-private',subcategory='test',detector=source,reason='Synthetic')]
      findings = rules.findings_for_page('doc',page,[],Context(),extra)
      layout.annotate(findings,[page],[])
      self.assertEqual(findings[0].review_signal,expected)
      self.assertTrue(findings[0].selected)

  def test_contacts_do_not_require_a_model(self):
    text = 'alice@example.com, +41 79 555 01 23, CH93 0076 2011 6238 5295 7.'
    fields = rules.rule_spans(text,Context())
    for kind in ['email','phone','account_number']:
      self.assertTrue(any(f['field_type']==kind for f in fields),kind)
