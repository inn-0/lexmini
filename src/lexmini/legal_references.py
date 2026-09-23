# src/lexmini/legal_references.py
"""Configurable Swiss citation patterns, with source portals labelled honestly.

A pattern match identifies a reference, not proof that a judgment exists.
Internal file numbers never receive an automatically constructed external link.
"""
import re
from urllib.parse import urlencode

PATTERNS = [
  ('bger_case', r'\b[1-9][A-Z]{1,3}_\d{1,6}\s*/\s*(?:19|20)\d{2}\b'),
  ('bvger_case', r'\b[A-F][-‐‑–]\d{1,6}\s*/\s*(?:19|20)\d{2}\b'),
  ('published_case', r'\b(?:BGE|ATF|DTF)\s+\d{1,3}\s+[IVX]{1,5}\s+\d{1,4}\b'),
  ('published_admin', r'\b(?:BVGE|ATAF|DTAF)\s+(?:19|20)\d{2}\s*/\s*\d{1,3}\b'),
  ('statute_article', r'\b[Aa]rt\.?\s*\d{1,3}[a-z]?(?:\s*(?:al\.?|Abs\.?|cpv\.?|para\.?)\s*\d+[a-z]?)?(?:\s*(?:let\.?|lit\.?)\s*[a-z])?(?:\s+(?:LAsi|LEI|LTAF|LTF|PA|Cst\.|CEDH|AsylG|AIG|VwVG|BGG|BV|ZGB|OR|StGB|CC|CO|CP))?'),
  ('statute_number', r'\b(?:RS|SR)\s+\d{1,3}(?:\.\d{1,4}){0,4}\b'),
  ('internal_file', r'(?i)\b(?:dossier|aktenzeichen|file\s*(?:no\.?|number)|réf(?:érence)?\.?|geschäftsnummer)\s*[:#]\s*[A-Z0-9][A-Z0-9_./-]{2,35}'),
]


def spans(text):
  for kind,pattern in PATTERNS:
    for match in re.finditer(pattern,text):
      yield dict(start=match.start(),end=match.end(),field_type='case_reference',
        level='professional-secrecy' if kind in {'internal_file','bvger_case','bger_case'} else 'public',
        subcategory=kind,detector='legal-reference-rule',
        reason='Legal reference pattern matched. Check whether it identifies this matter or cites a public source.')


def info(text, kind=''):
  normal=re.sub(r'\s+',' ',text).strip()
  if not kind or kind not in {k for k,_ in PATTERNS}:
    kind=next((k for k,p in PATTERNS if re.fullmatch(p,normal)), 'unresolved')
  if kind=='bger_case':
    return {'kind':kind,'url':'https://search.bger.ch/ext/eurospider/live/de/php/aza/http/index.php?'+urlencode({'type':'simple_query','lang':'de','query_words':normal}),'status':'Search official database - match not verified'}
  if kind in {'bvger_case','published_admin'}:
    return {'kind':kind,'url':'https://www.bvger.ch/de/rechtsprechung/entscheiddatenbank','status':'Open official database - search this reference'}
  if kind=='published_case':
    return {'kind':kind,'url':'https://www.bger.ch/ext/eurospider/live/fr/php/clir/http/index.php?lang=de&type=start','status':'Open official collection - search this reference'}
  if kind.startswith('statute'):
    return {'kind':kind,'url':'https://www.fedlex.admin.ch/de/cc','status':'Open Fedlex - article or law match not verified'}
  return {'kind':kind,'url':None,'status':'Internal or unresolved reference - no external link'}


def add_spacy_ruler(nlp):
  """Optional SpanRuler complements regex across token boundaries; keeps NER intact."""
  if 'lexmini_references' in nlp.pipe_names: return
  ruler=nlp.add_pipe('span_ruler',name='lexmini_references',config={'spans_key':'legal_references'})
  ruler.add_patterns([
    {'label':'LEGAL_REFERENCE','pattern':[{'TEXT':{'REGEX':r'^[1-9][A-Z]{1,3}_\d{1,6}/\d{4}$'}}]},
    {'label':'LEGAL_REFERENCE','pattern':[{'TEXT':{'REGEX':r'^[A-F]-\d{1,6}/\d{4}$'}}]},
    {'label':'LEGAL_REFERENCE','pattern':[{'TEXT':{'IN':['BGE','ATF','DTF']}},{'LIKE_NUM':True},{'TEXT':{'REGEX':'^[IVX]+$'}},{'LIKE_NUM':True}]},
  ])
