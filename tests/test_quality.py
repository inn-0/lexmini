# tests/test_quality.py
"""Saved public examples must match their source and must not call inference."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path as pPath
from unittest.mock import patch

from lexmini import pdf, quality, services
from lexmini.schemas import Context
from lexmini.screening_memory import ScreeningMemory
from test_review import fixture


class QualityTests(unittest.TestCase):
  def setUp(self):
    self.memory_directory = tempfile.TemporaryDirectory()
    self.memory_patch = patch('lexmini.services.memory', ScreeningMemory(pPath(self.memory_directory.name) / 'memory.json'))
    self.memory_patch.start()

  def tearDown(self):
    services.store.sessions.clear()
    self.memory_patch.stop()
    self.memory_directory.cleanup()

  def test_validated_cache_replay_and_tamper_rejection(self):
    payload = fixture()
    with tempfile.TemporaryDirectory() as directory:
      root = pPath(directory)
      (root / 'data/quality').mkdir(parents=True)
      (root / 'data/reference').mkdir()
      (root / 'data/reference/example.pdf').write_bytes(payload)
      record = {'schema_version':1, 'pdf_path':'data/reference/example.pdf',
        'pdf_sha256':hashlib.sha256(payload).hexdigest(), 'model':{'name':'test'},
        'pages':[{'text_sha256':hashlib.sha256(page.text.encode()).hexdigest(), 'spans':[]} for page in pdf.extract(payload).pages]}
      cache = root / 'data/quality/example.baseline.json'
      cache.write_text(json.dumps(record))
      screening = {'schema_version':1,'pdf_sha256':record['pdf_sha256'],'text_hashes':[p['text_sha256'] for p in record['pages']],
        'spacy_spans':[[]], 'regions':[], 'languages':['en'], 'engine':'synthetic-test'}
      (root / 'data/quality/example.screening.json').write_text(json.dumps(screening))
      with patch('lexmini._config.ROOT', root), patch('lexmini.services.screen_remote', side_effect=AssertionError('Remote inference must not run')), patch('lexmini.services.spacy_detector.detect', side_effect=AssertionError('Local inference must not run')):
        result = quality.load('example', Context())
        self.assertTrue(result.analysed)
        self.assertTrue(any(f.field_type == 'date' for f in result.findings))
        self.assertTrue(result.warnings)
        count = len(services.store.sessions)
        record['pages'][0]['text_sha256'] = 'wrong'
        cache.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, 'extracted text'):
          quality.load('example', Context())
        self.assertEqual(len(services.store.sessions), count)
        with self.assertRaises(KeyError):
          quality.load('../example', Context())
