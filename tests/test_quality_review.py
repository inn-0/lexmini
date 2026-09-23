# tests/test_quality_review.py
"""Validate edits, exact quotation mapping, human choices and real PDF grants."""
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from lexmini import services, quality, llm_review, legal_references, sharing
from lexmini.main import app
from lexmini.schemas import Context, QualityRequest, ReviewDecision

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
