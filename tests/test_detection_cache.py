# tests/test_detection_cache.py
# Rationale: repeat reviews must not repeat paid detection on unchanged input.
# Assumptions: workers return canonical hashes and offsets.
# Constraints: no remote requests; invalidate by source, language and organisation.
import hashlib
import unittest
from unittest.mock import MagicMock, patch
from test_compact_review import session_for
from lexmini import services
from lexmini.schemas import Context


class DetectionCacheTests(unittest.TestCase):
  def test_unchanged_role_reuses_workers_but_language_and_org_invalidate(self):
    session = session_for('Ordinary public text.')
    context = Context(use_privacy_filter=True, use_layout=False)
    worker = MagicMock()
    worker.detect.spawn.return_value.get.return_value = [[]]
    def screen(texts, languages, payload):
      return {'text_hashes':[hashlib.sha256(t.encode()).hexdigest() for t in texts],
        'pdf_sha256':None, 'spacy_spans':[[]], 'regions':[], 'engine':'unit'}
    with patch.object(services.store,'get',return_value=session), \
        patch.object(services,'screen_remote',side_effect=screen) as cpu, \
        patch.object(services.modal.Cls,'from_name',return_value=lambda:worker), \
        patch.object(services.memory,'for_screening',return_value=[]):
      services.analyse('compact-unit',context)
      services.analyse('compact-unit',context.model_copy(update={'role':'Different role'}))
      self.assertEqual(cpu.call_count,1)
      self.assertEqual(worker.detect.spawn.call_count,1)
      services.analyse('compact-unit',context.model_copy(update={'languages':['de']}))
      self.assertEqual(cpu.call_count,2)
      self.assertEqual(worker.detect.spawn.call_count,1)
      session.organisation_id='another-org'
      services.analyse('compact-unit',context)
      self.assertEqual(cpu.call_count,3)
      self.assertEqual(worker.detect.spawn.call_count,2)
    self.assertNotIn('screening_cache',session.model_dump())
    self.assertNotIn('privacy_cache',session.model_dump())

  def test_unverified_cpu_results_are_not_cached(self):
    session=session_for('Public text.')
    with patch.object(services.store,'get',return_value=session), \
        patch.object(services,'screen_remote',return_value={'text_hashes':['wrong']}):
      with self.assertRaisesRegex(ValueError,'hashes differ'):
        services.analyse('compact-unit',Context(use_layout=False))
    self.assertFalse(session.screening_cache)
