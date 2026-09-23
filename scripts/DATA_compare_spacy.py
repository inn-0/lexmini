# scripts/DATA_compare_spacy.py
# Rationale: compare an installed spaCy model with a frozen public PII run.
# Assumptions: run in an environment where the selected model is installed.
# Constraints: use public cached input, preserve exact offsets, install nothing,
# and keep benchmark output separate from the live review application's results.

import argparse
import hashlib
import json
import resource
import sys
import time
from collections import Counter
from importlib.metadata import version
from pathlib import Path as pPath

import spacy

ROOT = pPath(__file__).resolve().parents[1]


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('--model', default='fr_core_news_lg')
  args = parser.parse_args()
  folder = ROOT / 'data/quality'
  pages = json.loads((folder / 'audit_page_text.json').read_text())
  baseline = json.loads((folder / 'CH_BVGE_001_E-1088-2022_2022-11-07.baseline.json').read_text())
  assert len(pages) == len(baseline['pages'])
  for page, saved in zip(pages, baseline['pages']):
    assert hashlib.sha256(page['text'].encode()).hexdigest() == saved['text_sha256']
  started = time.perf_counter()
  nlp = spacy.load(args.model, exclude=['parser', 'lemmatizer', 'attribute_ruler', 'morphologizer', 'tagger'])
  assert 'ner' in nlp.pipe_names
  load_seconds = time.perf_counter() - started
  started = time.perf_counter()
  output = []
  for page, doc in zip(pages, nlp.pipe((p['text'] for p in pages), batch_size=4, n_process=1)):
    assert doc.text == page['text']
    output.append({'page':page['page'], 'text_sha256':hashlib.sha256(doc.text.encode()).hexdigest(),
      'spans':[{'start':ent.start_char,'end':ent.end_char,'text':ent.text,'label':ent.label_} for ent in doc.ents]})
  inference_seconds = time.perf_counter() - started
  checks = []
  for name in ['William Waeber','Gérald Bovier','David R. Wenger','Lucas Pellet','Charbel Fakhri-Kairouz']:
    start = pages[0]['text'].index(name)
    end = start + len(name)
    matched = [s for s in output[0]['spans'] if s['start'] < end and s['end'] > start]
    checks.append({'text':name,'start':start,'end':end,'spacy_matches':matched,
      'full_person_match':any(s['label'] in {'PER','PERSON'} and s['start']==start and s['end']==end for s in matched),
      'privacy_filter_full_match':any(s['start']<=start and s['end']>=end for s in baseline['pages'][0]['spans'])})
  counts = dict(Counter(s['label'] for p in output for s in p['spans']))
  model_path = pPath(nlp.path)
  result = {'schema_version':1,'input_pdf_sha256':baseline['pdf_sha256'],
    'spacy_version':spacy.__version__,'python_version':sys.version.split()[0],
    'model':args.model,'model_version':version(args.model.replace('_','-')),
    'components':nlp.pipe_names,'labels':list(nlp.get_pipe('ner').labels),
    'runtime':{'load_seconds':round(load_seconds,3),'inference_seconds':round(inference_seconds,3),
      'process_peak_rss_mb':round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024 / 1_000_000,1),
      'model_files_mb':round(sum(p.stat().st_size for p in model_path.rglob('*') if p.is_file())/1_000_000,1),
      'scope':'one local WSL process; not a Replit capacity measurement'},
    'entity_counts':counts,'cover_name_checks':checks,'pages':output,
    'limitations':'Five targeted cover-name checks; no complete gold entity inventory and no general precision/recall estimate.'}
  target = folder / f'{args.model}.comparison.json'
  target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
  print(json.dumps({k:result[k] for k in ['model','components','labels','runtime','entity_counts','cover_name_checks']},ensure_ascii=False,indent=2))


if __name__ == '__main__':
  main()
