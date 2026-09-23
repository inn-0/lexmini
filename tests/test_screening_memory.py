# tests/test_screening_memory.py
"""Reviewer examples must catch repeats without leaking stored source values.

Use isolated synthetic workspaces. Tests never read or modify local user memory.
"""

import json
import stat
import tempfile
import unittest
from pathlib import Path as pPath
from unittest.mock import patch

import pymupdf
from fastapi.testclient import TestClient

from lexmini import services
from lexmini.main import app
from lexmini.matching import find_matches
from lexmini.schemas import Context, LearnRequest
from lexmini.screening_memory import ScreeningMemory


def document(text):
  with pymupdf.open() as doc:
    doc.new_page().insert_text((50, 80), text)
    return doc.tobytes()


class MatchingTests(unittest.TestCase):
  def test_offsets_case_lines_and_word_boundaries(self):
    text = 'Alicia\n  Bernard; ALICIA BERNARD; Xalicia Bernardson'
    found = find_matches(text, 'Alicia Bernard', 'person_name', False)
    self.assertEqual([text[a:b] for a,b,_ in found], ['Alicia\n  Bernard', 'ALICIA BERNARD'])
    self.assertEqual(find_matches('Anna Ann Annette', 'Ann', 'person_name'), [(5,8,'exact')])

  def test_fuzzy_is_bounded_and_not_for_numbers_or_secrets(self):
    self.assertTrue(find_matches('Alicia Bernrad', 'Alicia Bernard', 'person_name'))
    self.assertTrue(find_matches('Alicia Bernrd', 'Alicia Bernard', 'person_name'))
    self.assertEqual(find_matches('Alicia Bernxxd', 'Alicia Bernard', 'person_name'), [])
    for text, term, kind in [('2026-10-02','2026-10-01','date'), ('12345679','12345678','account_number'),
      ('secretpasswore','secretpassword','credential'), ('Annb','Anna','person_name')]:
      self.assertEqual(find_matches(text,term,kind), [])


class ScreeningTests(unittest.TestCase):
  def setUp(self):
    self.directory = tempfile.TemporaryDirectory()
    self.path = pPath(self.directory.name) / 'private/memory.json'
    self.memory = ScreeningMemory(self.path)
    self.override = patch('lexmini.services.memory', self.memory)
    self.override.start()

  def tearDown(self):
    self.override.stop()
    services.store.sessions.clear()
    self.directory.cleanup()

  def analyse(self, text, review_set='matter-a'):
    review = services.store.create(document(text),'synthetic.pdf')
    return services.apply_predictions(review.document_id, Context(review_set=review_set), [[]])

  def test_later_documents_use_confirmed_memory_and_set_scope(self):
    first = self.analyse('Alicia Bernard met Alicia Bernard.')
    learned = services.learn(first.document_id, LearnRequest(revision=first.revision,
      text='Alicia Bernard',field_type='person_name',sensitivity_levels=['personal-private'],remember=True))
    self.assertEqual(len([f for f in learned.findings if f.field_type=='person_name']),2)
    self.assertEqual(stat.S_IMODE(self.path.stat().st_mode),0o600)
    # A fresh store instance proves the examples survive server restart.
    with patch('lexmini.services.memory',ScreeningMemory(self.path)):
      later = self.analyse('Alicia Bernrad visited today.')
    matches = [f for f in later.findings if 'screening-memory-fuzzy' in f.detector]
    self.assertEqual(len(matches),1)
    self.assertEqual(matches[0].original_text,'Alicia Bernrad')
    self.assertNotIn('Alicia Bernard', later.model_dump_json())
    self.assertNotIn('origin_document_hash', later.model_dump_json())
    elsewhere = self.analyse('Alicia Bernard visited today.', 'matter-b')
    self.assertFalse(any('screening-memory' in f.detector for f in elsewhere.findings))

  def test_predictions_do_not_automatically_enter_memory(self):
    review = services.store.create(document('Alicia Bernard met Alicia Bernard.'),'synthetic.pdf')
    text = services.store.get(review.document_id).extracted.pages[0].text
    start = text.index('Alicia Bernard')
    result = services.apply_predictions(review.document_id, Context(), [[{
      'start':start,'end':start+14,'text':'Alicia Bernard','label':'private_person'}]])
    self.assertEqual(len([f for f in result.findings if f.field_type=='person_name']),2)
    self.assertFalse(self.path.exists())

  def test_two_documents_teach_later_documents_without_learning_fuzzy_guesses(self):
    for term in ['Project Evergreen','Project Blackwood']:
      first = self.analyse(term + ' is confidential.')
      services.learn(first.document_id, LearnRequest(revision=first.revision,text=term,field_type="organisation_name",remember=True))
    saved = self.path.read_bytes()
    for _ in range(3):
      later = self.analyse('Project Evergreem and Project Blackwood are mentioned.')
      terms = [f.original_text for f in later.findings if 'screening-memory' in f.detector]
      self.assertIn('Project Evergreem',terms)
      self.assertIn('Project Blackwood',terms)
    self.assertEqual(self.path.read_bytes(),saved)

  def test_bad_private_record_does_not_leak_in_error(self):
    self.path.parent.mkdir()
    self.path.write_text(json.dumps({'version':1,'terms':[{'text':'PRIVATE EXAMPLE VALUE'}]}))
    with self.assertRaises(ValueError) as error:
      self.memory.for_screening('matter-a')
    self.assertNotIn('PRIVATE EXAMPLE VALUE', str(error.exception))

  def test_document_only_and_invalid_terms_do_not_persist(self):
    first = self.analyse('Project Evergreen is mentioned.')
    result = services.learn(first.document_id, LearnRequest(revision=first.revision,
      text='Project Evergreen',remember=False))
    self.assertTrue(any('reviewer-example' in f.detector for f in result.findings))
    self.assertFalse(self.path.exists())
    with self.assertRaisesRegex(ValueError,'must occur'):
      services.learn(first.document_id, LearnRequest(revision=result.revision,text='Absent secret'))
    with self.assertRaisesRegex(ValueError,'Review changed'):
      services.learn(first.document_id, LearnRequest(revision=0,text='Project Evergreen'))

  def test_failed_save_does_not_change_review_and_kept_selection_survives(self):
    review = self.analyse('Project Evergreen on 2026-10-01.')
    date = next(f for f in review.findings if f.field_type=='date')
    request = LearnRequest(revision=review.revision,text='Project Evergreen',field_type='organisation_name',kept_ids=[date.finding_id],remember=True)
    with patch.object(self.memory,'remember',side_effect=OSError('Synthetic write failure')):
      with self.assertRaises(OSError):
        services.learn(review.document_id,request)
    self.assertEqual(services.store.get(review.document_id).review.model_dump(),review.model_dump())
    result = services.learn(review.document_id,request)
    self.assertFalse(next(f for f in result.findings if f.finding_id==date.finding_id).selected)

  def test_learning_endpoint_requires_browser_boundary_and_no_listing(self):
    review = self.analyse('Project Evergreen is mentioned.')
    with TestClient(app) as client:
      payload = {'revision':review.revision,'text':'Project Evergreen'}
      self.assertEqual(client.post(f'/api/documents/{review.document_id}/learn',json=payload).status_code,403)
      response = client.post(f'/api/documents/{review.document_id}/learn',json=payload,headers={'X-Lexmini-Client':'review'})
      self.assertEqual(response.status_code,200)
      self.assertNotIn('origin_document_hash',response.text)
      self.assertEqual(client.get('/api/screening-memory').status_code,404)
