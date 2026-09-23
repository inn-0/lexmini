# src/lexmini/legal_references.py
"""Swiss citation anchors and honest links to official search portals.

Reference recognition does not establish confidentiality or verify existence.
Internal file numbers never receive an automatically constructed external link.
"""
import re
from urllib.parse import urlencode

YEAR = r'(?:19|20)\d{2}'
SUFFIX = r'(?:bis|ter|quater|quinquies|sexies|septies|octies|nonies|decies|[a-z])?'
NUMBER = rf'\d{{1,3}}{SUFFIX}(?!\w)'
LAW = r'(?:TS-TAF|ComComV|aComComV|GebV-FMG|LAsi|LEI|LTAF|LTF|LPGA|LAVS|LAI|OAI|PA|Cst\.|CEDH|AsylG|AIG|VwVG|BGG|BV|ZGB|OR|StGB|CC|CO|CP|FMG|FDV)(?!\w)'
ARTICLE_ITEM = rf'{NUMBER}(?:\s*[-–]\s*{NUMBER})?(?:\s+(?:al\.?|Abs\.?|cpv\.?|para\.?)\s*{NUMBER})?(?:\s+(?:lett?\.?|lit\.?|Bst\.?)\s*[a-z]{SUFFIX}(?!\w))?(?:\s+ch\.?\s*\d+)?(?:\s+(?:e\s+segg\.|et\s+suiv\.|ff\.))?'
ARTICLE = rf'\b(?:aArt|[Aa]rt)\.?\s*{ARTICLE_ITEM}(?:\s*(?:,\s*|(?:et|e|und)\s+){ARTICLE_ITEM})*(?:\s+{LAW}(?:\s+{YEAR})?)?'
PINPOINT = r'(?:\s+(?:consid\.|E\.)\s*\d+(?:\.\d+)*[a-z]?)?'
PATTERNS = [
  ('bger_case', rf'\b[1-9][A-Z]{{1,3}}[_.]\d{{1,6}}\s*/\s*{YEAR}\b'),
  ('bvger_case', rf'\b[A-F][-‐‑–]\d{{1,6}}\s*/\s*{YEAR}\b'),
  ('published_case', rf'\b(?:BGE|ATF|DTF)\s+\d{{1,3}}\s+[IVX]{{1,5}}\s+\d{{1,4}}\b{PINPOINT}'),
  ('published_admin', rf'\b(?:BVGE|ATAF|DTAF)\s+{YEAR}\s*(?:[IVX]{{1,5}}\s*)?/\s*\d{{1,3}}\b{PINPOINT}'),
  ('statute_article', ARTICLE),
  ('statute_number', r'\b(?:RS|SR)\s+\d{1,3}(?:\.\d{1,4}){0,4}\b'),
  ('statute_publication', rf'\b(?:AS|RO|RU|FF|BBl)\s+{YEAR}\s+\d{{1,6}}(?:,\s*(?:spéc\.|S\.|p\.)\s*\d+)?\b'),
  ('legacy_asylum', rf'\b(?:JICRA|GICRA|EMARK)\]?\s+{YEAR}\s+(?:n°|n\.|Nr\.?)\s*\d+\b{PINPOINT}'),
  ('echr_application', r'\b(?:requêtes?\s+n[°o]|no)\s+\d{1,6}/\d{2}\b'),
  ('internal_file', r'(?i)\b(?:dossier|aktenzeichen|file\s*(?:no\.?|number)|réf(?:érence)?\.?|geschäftsnummer)\s*[:#]\s*[A-Z0-9][A-Z0-9_./-]{2,35}'),
]


def _matches(text):
  for kind, pattern in PATTERNS:
    for match in re.finditer(pattern, text):
      yield kind, match.start(), match.end()
      # Bare year/number citations inherit the collection only in an immediate list.
      if kind == 'published_admin':
        cursor = match.end()
        while continuation := re.match(rf'\s*;\s*(?P<reference>{YEAR}/\d{{1,3}}\b{PINPOINT})', text[cursor:]):
          start, end = continuation.span('reference')
          yield 'published_admin_inherited', cursor + start, cursor + end
          cursor += continuation.end()


def spans(text):
  seen = set()
  for kind, start, end in _matches(text):
    if (start, end) in seen:
      continue
    seen.add((start, end))
    yield dict(start=start, end=end, field_type='case_reference',
      level='professional-secrecy' if kind == 'internal_file' else 'public',
      subcategory=kind, detector='legal-reference-rule',
      reason='Legal reference pattern matched; public unless explicit matter instructions establish confidentiality.')


def info(text, kind=''):
  normal = re.sub(r'\s+', ' ', text).strip()
  known = {k for k, _ in PATTERNS} | {'published_admin_inherited'}
  if not kind or kind not in known:
    kind = next((k for k, p in PATTERNS if re.fullmatch(p, normal)), 'unresolved')
  if kind == 'bger_case':
    return {'kind':kind, 'url':'https://search.bger.ch/ext/eurospider/live/de/php/aza/http/index.php?' + urlencode({'type':'simple_query','lang':'de','query_words':normal}), 'status':'Search official database - match not verified'}
  if kind in {'bvger_case', 'published_admin', 'published_admin_inherited', 'legacy_asylum'}:
    return {'kind':kind, 'url':'https://www.bvger.ch/de/rechtsprechung/entscheiddatenbank', 'status':'Open official database - search this reference'}
  if kind == 'published_case':
    return {'kind':kind, 'url':'https://www.bger.ch/ext/eurospider/live/fr/php/clir/http/index.php?lang=de&type=start', 'status':'Open official collection - search this reference'}
  if kind.startswith('statute'):
    return {'kind':kind, 'url':'https://www.fedlex.admin.ch/de/cc', 'status':'Open Fedlex - article or law match not verified'}
  if kind == 'echr_application':
    return {'kind':kind, 'url':'https://hudoc.echr.coe.int/', 'status':'Open official database - search this reference'}
  return {'kind':kind, 'url':None, 'status':'Internal or unresolved reference - no external link'}


def add_spacy_ruler(nlp):
  """Store citation spans separately, preserving the existing named entities."""
  if 'lexmini_references' in nlp.pipe_names:
    return
  ruler = nlp.add_pipe('span_ruler', name='lexmini_references', config={'spans_key':'legal_references', 'annotate_ents':False})
  ruler.add_patterns([
    {'label':'LEGAL_REFERENCE', 'pattern':[{'TEXT':{'REGEX':r'^[1-9][A-Z]{1,3}[_.]\d{1,6}/\d{4}$'}}]},
    {'label':'LEGAL_REFERENCE', 'pattern':[{'TEXT':{'REGEX':r'^[A-F][-‐‑–]\d{1,6}/\d{4}$'}}]},
    {'label':'LEGAL_REFERENCE', 'pattern':[{'TEXT':{'IN':['BGE','ATF','DTF']}}, {'LIKE_NUM':True}, {'TEXT':{'REGEX':r'^[IVX]+$'}}, {'LIKE_NUM':True}]},
    {'label':'LEGAL_REFERENCE', 'pattern':[{'TEXT':{'IN':['BVGE','ATAF','DTAF']}}, {'TEXT':{'REGEX':r'^\d{4}/\d{1,3}$'}}]},
    {'label':'LEGAL_REFERENCE', 'pattern':[{'TEXT':{'IN':['BVGE','ATAF','DTAF']}}, {'LIKE_NUM':True}, {'TEXT':{'REGEX':r'^[IVX]+/\d{1,3}$'}}]},
    {'label':'LEGAL_REFERENCE', 'pattern':[{'TEXT':{'IN':['RS','SR']}}, {'TEXT':{'REGEX':r'^\d{1,3}(?:\.\d{1,4}){1,4}$'}}]},
    # German tokenisation splits slash-separated identifiers into several tokens.
    {'label':'LEGAL_REFERENCE', 'pattern':[{'TEXT':{'REGEX':r'^[1-9][A-Z]{1,3}[_.]\d{1,6}$'}}, {'TEXT':'/'}, {'TEXT':{'REGEX':r'^(?:19|20)\d{2}$'}}]},
    {'label':'LEGAL_REFERENCE', 'pattern':[{'TEXT':{'REGEX':r'^[A-F][-‐‑–]\d{1,6}$'}}, {'TEXT':'/'}, {'TEXT':{'REGEX':r'^(?:19|20)\d{2}$'}}]},
    {'label':'LEGAL_REFERENCE', 'pattern':[{'TEXT':{'IN':['BVGE','ATAF','DTAF']}}, {'TEXT':{'REGEX':r'^(?:19|20)\d{2}$'}}, {'TEXT':{'REGEX':r'^[IVX]+$'}, 'OP':'?'}, {'TEXT':'/'}, {'LIKE_NUM':True}]},
  ])
