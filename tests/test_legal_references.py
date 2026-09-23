# tests/test_legal_references.py
"""Source-grounded citation anchors, false positives and spaCy entity preservation."""
import json
from pathlib import Path as pPath

import unittest

from lexmini.legal_references import add_spacy_ruler, info, spans

FIXTURE = json.loads((pPath(__file__).parent/'fixtures/swiss_citations.json').read_text())


def check_real_citation_anchors(example):
  text = example['text']
  target_start = example['target_start']
  target_end = target_start + len(example['quote'])
  found = list(spans(text))
  if not example['expected']:
    assert not [s for s in found if s['start'] < target_end and s['end'] > target_start]
    return
  for quote in example['expected']:
    start = text.index(quote, target_start)
    assert any(s['start'] == start and s['end'] == start + len(quote) for s in found), quote
  assert all(s['level'] == 'public' for s in found)


def check_bare_numbers_need_immediate_collection_context():
  assert not list(spans('Costs 2009/50; 2008/24. Report 2012/21.'))
  text = 'ATAF 2009/60 consid. 2.1.1; 2009/50 consid. 10.2; 2008/24 consid. 7.2'
  assert [text[s['start']:s['end']] for s in spans(text)] == [
    'ATAF 2009/60 consid. 2.1.1', '2009/50 consid. 10.2', '2008/24 consid. 7.2']
  assert not [s for s in spans('ATAF 2009/60. Sales year 2008/24') if s['subcategory'].endswith('inherited')]


def check_internal_reference_has_no_external_link():
  item = list(spans('Dossier: PRIVATE-2049'))[0]
  assert item['level'] == 'professional-secrecy'
  assert info('Dossier: PRIVATE-2049')['url'] is None
  assert info('2A.586/2003')['kind'] == 'bger_case'
  assert info('Directive 2O11l95lUE')['kind'] == 'unresolved'


def check_ruler_preserves_named_entities_and_is_idempotent(language):
  import spacy
  from spacy.tokens import Span
  nlp = spacy.blank(language)
  add_spacy_ruler(nlp)
  add_spacy_ruler(nlp)
  assert nlp.pipe_names.count('lexmini_references') == 1
  doc = nlp.make_doc('Swisscom BGE 125 II 473 2A.586/2003 BVGE 2017 I/4')
  doc.ents = [Span(doc, 0, 1, label='ORG')]
  doc = nlp.get_pipe('lexmini_references')(doc)
  assert [(e.text,e.label_) for e in doc.ents] == [('Swisscom','ORG')]
  assert {'BGE 125 II 473','2A.586/2003','BVGE 2017 I/4'} <= {s.text for s in doc.spans['legal_references']}


class LegalReferenceTests(unittest.TestCase):
  def test_source_examples(self):
    for example in FIXTURE['examples']:
      with self.subTest(example=example['id']):
        check_real_citation_anchors(example)

  def test_context(self):
    check_bare_numbers_need_immediate_collection_context()

  def test_links(self):
    check_internal_reference_has_no_external_link()

  def test_spacy(self):
    for language in ('de', 'fr', 'it', 'en'):
      with self.subTest(language=language):
        check_ruler_preserves_named_entities_and_is_idempotent(language)
