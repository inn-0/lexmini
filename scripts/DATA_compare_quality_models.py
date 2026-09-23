# scripts/DATA_compare_quality_models.py
# Rationale: compare a cheaper and stronger model against the same public excerpts.
# Assumptions: OpenAI key in the environment and real reference fixtures available.
# Constraints: no invented document text; saved outputs contain public examples only.
import json
import time
from pathlib import Path as pPath
from concurrent.futures import ThreadPoolExecutor
from lexmini import _config, pdf, paragraphs, llm_review
from lexmini.layout import LayoutRegion

ROOT=pPath(__file__).resolve().parents[1]


def main():
  name='CH_BVGE_001_E-1088-2022_2022-11-07'
  baseline=json.loads((ROOT/f'data/quality/{name}.baseline.json').read_text())
  cache=json.loads((ROOT/f'data/quality/{name}.screening.json').read_text())
  pages=pdf.extract((ROOT/baseline['pdf_path']).read_bytes()).pages
  regions=[LayoutRegion.model_validate(r) for r in cache['regions']]
  medical=next(p.text for p in paragraphs.build(pages[4],regions) if 'diagnostic' in p.text)
  citation=next(p.text for page in pages for p in paragraphs.build(page,regions) if 'ATAF 2015/11' in p.text)
  header=pages[0].text
  specs=[('medical',medical,[('Relaxane','address','medical_information'),('Quétiapine','address','medical_information')]),
    ('citation',citation,[('ATAF 2015/11','organisation_name','case_reference')]),
    ('parties',header,[('William Waeber','person_name','protect'),('Charbel Fakhri-Kairouz','person_name','protect')])]
  expected={};blocks=[]
  for name,text,items in specs:
    candidates=[]
    for quote,kind,want in items:
      assert quote in text,(name,quote)
      identifier=f'{name}-{len(candidates)}';expected[identifier]=want
      candidates.append({'id':identifier,'type':kind,'quote':quote,'selected':True,'levels':['professional-secrecy']})
    blocks.append({'id':name,'page':1,'text':text,'candidates':candidates})
  payload={'role':'Legal translator','goal':'Translate while concealing private parties. Keep ordinary timeline dates and legal citations.','first_pages_context':header,'blocks':blocks}
  def run(model):
    begin=time.monotonic();result,usage=llm_review.call(payload,model)
    changes={c.finding_id:c for c in result.changes};checks={}
    for identifier,want in expected.items():
      change=changes.get(identifier)
      if want=='keep': passed=bool(change and change.action=='keep')
      elif want=='protect': passed=change is None or change.action!='keep'
      else: passed=bool(change and change.field_type==want)
      checks[identifier]=passed
    valid_quotes=all(a.block_id in {b['id'] for b in blocks} and a.quote in next(b['text'] for b in blocks if b['id']==a.block_id) for a in result.additions)
    checks['additions_are_exact_quotes']=valid_quotes
    return {'model':model,'seconds':round(time.monotonic()-begin,2),'usage':usage,'checks':checks,'passed':sum(checks.values()),'total':len(checks),'result':result.model_dump()}
  with ThreadPoolExecutor(max_workers=2) as pool:
    results=list(pool.map(run,['gpt-4.1-mini','gpt-4.1']))
  destination=ROOT/'data/quality/llm_model_comparison_swiss_fr.json'
  destination.write_text(json.dumps({'source':'Real French Swiss Federal Administrative Court judgment E-1088/2022, 7 November 2022','payload':payload,'results':results},ensure_ascii=False,indent=2)+'\n')
  for result in results: print(json.dumps({k:v for k,v in result.items() if k!='result'}),flush=True)


if __name__=='__main__':
  main()
