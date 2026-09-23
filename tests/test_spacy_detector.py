# tests/test_spacy_detector.py
"""Check actual French model offsets and retention through reviewer updates.

Use synthetic text and temporary memory; do not write to the user's memory.
"""

import tempfile
import unittest
from pathlib import Path as pPath
from unittest.mock import patch

from lexmini import services, spacy_detector
from lexmini.schemas import Context, LearnRequest
from lexmini.screening_memory import ScreeningMemory
from test_screening_memory import document
from test_review import empty_screen


def actual_local_screen(texts, languages, payload):
  result = empty_screen(texts, languages, payload)
  result['spacy_spans'] = spacy_detector.detect(texts, languages)
  return result


class SpacyTests(unittest.TestCase):
  def tearDown(self):
    services.store.sessions.clear()

  def test_french_cover_names_have_exact_offsets(self):
    text = 'Composition : William Waeber, Gérald Bovier, David R. Wenger, juges ; Lucas Pellet, greffier. Charbel Fakhri-Kairouz, avocat.'
    spans = spacy_detector.detect([text, ''], ['fr'])
    self.assertEqual(spans[1], [])
    names = {text[s['start']:s['end']] for s in spans[0] if s['field_type'] == 'person_name'}
    self.assertTrue({'William Waeber', 'Gérald Bovier', 'Lucas Pellet'} <= names)
    self.assertTrue(all(s['detector'] == 'spacy/fr_core_news_lg@3.8.0' for s in spans[0]))

  def test_spacy_findings_survive_manual_reanalysis(self):
    with tempfile.TemporaryDirectory() as directory, patch('lexmini.services.screen_remote', side_effect=actual_local_screen):
      with patch('lexmini.services.memory', ScreeningMemory(pPath(directory) / 'memory.json')):
        review = services.store.create(document('William Waeber, juge. Dossier Omega.'), 'synthetic.pdf')
        result = services.analyse(review.document_id, Context(languages=['fr']))
        names = {f.finding_id for f in result.findings if 'spacy/' in f.detector}
        self.assertTrue(names)
        updated = services.learn(review.document_id, LearnRequest(revision=result.revision,
          text='Dossier Omega', field_type='confidential_term', sensitivity_levels=['professional-secrecy'], remember=False))
        self.assertTrue(names <= {f.finding_id for f in updated.findings})

  def test_unsupported_language_fails(self):
    with self.assertRaisesRegex(ValueError, 'supported spaCy language'):
      spacy_detector.detect(['Example'], ['xx'])
