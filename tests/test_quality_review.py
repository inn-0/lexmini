# tests/test_quality_review.py
"""Validate edits, exact quotation mapping, human choices and real PDF grants."""
import unittest
import time
from unittest.mock import patch
from fastapi.testclient import TestClient
from lexmini import services, quality, llm_review, legal_references, sharing
from lexmini.main import app
from lexmini.schemas import Context, QualityRequest, ReviewDecision, Finding, Location, DocumentReview, PageInfo

SAMPLE='CUAD_07_Hosting'


class QualityTests(unittest.TestCase):
  def tearDown(self):
    services.store.sessions.clear()
    sharing._grants.clear()

  def sample(self):
    return quality.load(SAMPLE,Context())

  def test_refs_and_exact_quotes_are_validated(self):
    review=self.sample();session=services.store.get(review.document_id)
    def fake(payload):
      block=payload['blocks'][0]
      valid_quote=block['text'][:20]
      result=llm_review.Result(suggested_role='Translator',suggested_goal='Translate',changes=[
        llm_review.Change(finding_id='invented-id',action='keep',field_type='date',sensitivity_levels=['public'],reason='bad')],additions=[
        llm_review.Addition(block_id=block['id'],quote='text that is not in this source XYZ',occurrence=1,field_type='case_reference',sensitivity_levels=['public'],reason='bad'),
        llm_review.Addition(block_id=block['id'],quote=valid_quote,occurrence=1,field_type='case_reference',sensitivity_levels=['public'],reason='exact')])
      return result,{'input_tokens':1,'output_tokens':1}
    with patch('lexmini.llm_review.call',side_effect=fake):
      result=llm_review.review(session)
    self.assertGreater(result['rejected'],0)
    self.assertEqual(result['changes'],[])
    self.assertTrue(result['additions'])

  def test_human_decision_survives_llm(self):
    review=self.sample();finding=next(f for f in review.findings if f.field_type=='organisation_name')
    change=llm_review.Change(finding_id=finding.finding_id,action='keep',field_type='organisation_name',sensitivity_levels=['public'],reason='Ignore human')
    result={'changes':[change],'additions':[],'suggested_role':'Translator','suggested_goal':'Translate','batches':1,'usage':{},'rejected':0,'model':'test'}
    with patch('lexmini.llm_review.review',return_value=result):
      updated=services.quality_review(review.document_id,QualityRequest(revision=review.revision,decisions=[ReviewDecision(finding_id=finding.finding_id,selected=True,review_status='confirmed_remove')]))
    self.assertTrue(next(f for f in updated.findings if f.finding_id==finding.finding_id).selected)
    self.assertEqual(updated.quality_check['protected'],1)

  def fixture(self, text='ATF 147 II 1 and Example SA'):
    page=services.pdf.PageText(text=text,boxes=[None]*len(text),lines=[0]*len(text),
      info=PageInfo(number=1,width=600,height=800,readable=True))
    review=DocumentReview(document_id='unit',filename='unit.pdf',page_count=1,pages=[page.info],analysed=True)
    session=services.Session(payload=b'',extracted=services.pdf.ExtractedPDF(pages=[page]),review=review,expires=time.monotonic()+600)
    services.store.sessions['unit']=session
    return session

  def candidate(self, session, ident, start, end, field_type='person_name', **overrides):
    values=dict(finding_id=ident,original_text=session.extracted.pages[0].text[start:end],field_type=field_type,
      location=Location(page_number=1,start=start,end=end),sensitivity_levels=['personal-private'],
      subcategory='identity',detector='openai/privacy-filter',reason='Machine candidate')
    values.update(overrides)
    finding=Finding(**values)
    session.review.findings.append(finding)
    return finding

  def check(self, session, changes=None, additions=None):
    result={'changes':changes or [],'additions':additions or [],'model':'test'}
    with patch('lexmini.llm_review.review',return_value=result):
      return services.quality_review('unit',QualityRequest(revision=session.review.revision))

  def keep(self, finding, field_type='organisation_name'):
    return llm_review.Change(finding_id=finding.finding_id,action='keep',field_type=field_type,
      sensitivity_levels=['public'],reason='Public citation or reference, not a client')

  def test_machine_person_can_be_corrected_but_approved_memory_cannot(self):
    session=self.fixture()
    machine=self.candidate(session,'machine',16,26)
    memory=self.candidate(session,'memory',16,26,detector='screening-memory')
    human=self.candidate(session,'human',16,26,review_status='confirmed_remove')
    result=self.check(session,[self.keep(f) for f in [machine,memory,human]])
    findings={f.finding_id:f for f in result.findings}
    self.assertFalse(findings['machine'].selected)
    self.assertEqual(findings['machine'].field_type,'organisation_name')
    self.assertTrue(findings['memory'].selected)
    self.assertTrue(findings['human'].selected)
    self.assertEqual(result.quality_check['protected'],2)

  def test_public_citation_clears_fragments_preserves_sensitive_and_partial_spans(self):
    session=self.fixture()
    citation=self.candidate(session,'citation',0,12,'case_reference')
    fragment=self.candidate(session,'fragment',4,7,'date')
    sensitive=self.candidate(session,'sensitive',4,7,'birth_date')
    human=self.candidate(session,'human',4,7,'date',review_status='confirmed_remove')
    partial=self.candidate(session,'partial',10,17)
    result=self.check(session,[self.keep(citation,'case_reference')])
    findings={f.finding_id:f for f in result.findings}
    self.assertFalse(findings['fragment'].selected)
    for ident in ['sensitive','human','partial']:
      self.assertTrue(findings[ident].selected,ident)
    self.assertEqual(result.quality_check['reconciled'],1)

  def test_explicit_protect_change_survives_outer_keep(self):
    session=self.fixture()
    outer=self.candidate(session,'outer',0,12,'case_reference')
    inner=self.candidate(session,'inner',4,7,'date')
    protect=llm_review.Change(finding_id=inner.finding_id,action='remove',field_type='date',
      sensitivity_levels=['personal-private'],reason='Independent sensitive date')
    result=self.check(session,[protect,self.keep(outer,'case_reference')])
    self.assertTrue(next(f for f in result.findings if f.finding_id=='inner').selected)

  def test_added_keep_applies_action_and_reconciles_fragment(self):
    session=self.fixture()
    self.candidate(session,'fragment',4,7,'date')
    addition=dict(page=1,start=0,end=12,field_type='case_reference',levels=['public'],
      action='keep',reason='Public legal citation')
    result=self.check(session,additions=[addition])
    added=next(f for f in result.findings if f.finding_id!='fragment')
    self.assertFalse(added.selected)
    self.assertEqual(added.context_suggestion,'keep')
    self.assertFalse(next(f for f in result.findings if f.finding_id=='fragment').selected)

  def test_added_review_date_overrides_ordinary_date_default(self):
    session=self.fixture('The meeting was on 29 April 2021.')
    addition=dict(page=1,start=19,end=32,field_type='date',levels=['professional-secrecy'],
      action='review',reason='Potentially sensitive meeting date')
    result=self.check(session,additions=[addition])
    added=next(f for f in result.findings if 'openai-quality' in f.detector)
    self.assertTrue(added.selected)
    self.assertEqual(added.context_suggestion,'review')

  def test_addition_inherits_exact_human_keep_across_types(self):
    session=self.fixture()
    self.candidate(session,'human',0,12,review_status='confirmed_keep',selected=False)
    result=self.check(session,additions=[dict(page=1,start=0,end=12,field_type='case_reference',
      levels=['public'],action='remove',reason='Model contradicts reviewer')])
    added=next(f for f in result.findings if f.finding_id!='human')
    self.assertFalse(added.selected)
    self.assertEqual(added.review_status,'confirmed_keep')
    self.assertIn('Inherited',added.context_reason)

  def test_addition_conflicting_human_states_prefers_removal(self):
    session=self.fixture()
    self.candidate(session,'keep',0,12,review_status='confirmed_keep',selected=False)
    self.candidate(session,'memory',0,12,'organisation_name',detector='screening-memory')
    result=self.check(session,additions=[dict(page=1,start=0,end=12,field_type='case_reference',
      levels=['public'],action='keep',reason='Public citation')])
    added=next(f for f in result.findings if f.finding_id not in {'keep','memory'})
    self.assertTrue(added.selected)
    self.assertEqual(added.review_status,'confirmed_remove')
    self.assertIn('Conflicting human decisions',added.context_reason)
    self.assertIn('keep',added.context_reason)
    self.assertIn('memory',added.context_reason)

  def test_reference_patterns_and_unresolved_links(self):
    text='ATF 147 II 1; E-1088/2022; 1C_170/2024; ATAF 2015/11; art. 3 CEDH; dossier: SECRET-42'
    found=list(legal_references.spans(text))
    self.assertEqual(len(found),6)
    self.assertIsNone(legal_references.info('dossier: SECRET-42','internal_file')['url'])
    self.assertIsNone(legal_references.info('imaginary citation')['url'])
    self.assertIn('not verified',legal_references.info('1C_170/2024')['status'])

  def test_real_document_share_expiry_revocation_and_version(self):
    review=self.sample()
    with TestClient(app) as client:
      headers={'X-Lexmini-Client':'review'}
      url=f'/api/documents/{review.document_id}/share'
      body={'revision':review.revision,'recipient':'Translator','selected_ids':[f.finding_id for f in review.findings if f.selected],'expires_in':60}
      issue=client.post(url,headers=headers,json=body)
      self.assertEqual(issue.status_code,200)
      grant=issue.json()
      self.assertTrue(client.get(grant['url']).content.startswith(b'%PDF'))
      self.assertEqual(client.post(url+'/'+grant['token']+'/revoke',headers=headers).status_code,200)
      self.assertEqual(client.get(grant['url']).status_code,403)
      grant=client.post(url,headers=headers,json=body).json()
      sharing._grants[grant['token']]['expires_at']=0
      self.assertEqual(client.get(grant['url']).status_code,403)
      grant=client.post(url,headers=headers,json=body).json()
      services.store.get(review.document_id).review.revision+=1
      self.assertEqual(client.get(grant['url']).status_code,403)
      audit=client.get(f'/api/documents/{review.document_id}/share-audit').json()
      self.assertTrue(any(e['action']=='grant_issued' and e['expires_in']==60 for e in audit))


if __name__=='__main__':
  unittest.main()
