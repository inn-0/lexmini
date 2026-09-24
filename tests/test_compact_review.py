# tests/test_compact_review.py
# Rationale: validate sparse model quotations before changing review decisions.
# Assumptions: unit fixtures are artificial and make no benchmark-quality claims.
# Constraints: no provider requests; preserve human decisions and atomic cache writes.
import copy
import time
import unittest
from collections import Counter
from unittest.mock import patch

from lexmini import compact_review as compact, llm_review, paragraphs, pdf, services
from lexmini.schemas import Context, DocumentReview, Finding, Location, PageInfo, QualityRequest


def session_for(text, findings=None):
  info = PageInfo(number=1, width=600, height=800, readable=True)
  page = pdf.PageText(text=text, boxes=[(10,10,20,20)]*len(text), lines=[0]*len(text), info=info)
  return services.Session(payload=b'%PDF-unit-fixture', extracted=pdf.ExtractedPDF(pages=[page]),
    review=DocumentReview(document_id='compact-unit', filename='unit.pdf', page_count=1,
      pages=[info], analysed=True, findings=findings or [], revision=1),
    expires=time.monotonic()+120, context=Context(), organisation_id='unit-org')


def block(text, start=0, identifier='B1'):
  return identifier, paragraphs.Paragraph(page_number=1, text=text,
    offsets=list(range(start,start+len(text))), source='unit-fixture', label='paragraph')


def answer(payload, spans=None):
  return compact.Result(reviewed=[b['id'] for b in payload['blocks']], spans=spans or []), {
    'input_tokens':31, 'output_tokens':7, 'requests':1}


def span(quote, block_id='B1', occurrence=1, kind='medical_information'):
  return compact.Span(block=block_id, quote=quote, occurrence=occurrence, kind=kind, action='hide')


class CompactValidationTests(unittest.TestCase):
  def test_every_block_must_be_acknowledged_once(self):
    batch=[{'id':'B1','text':'No fracture.'},{'id':'B2','text':'Public facts.'}]
    for reviewed in (['B1'], ['B1','B1'], ['B1','B2','B2'], ['B1','B3']):
      with self.subTest(reviewed=reviewed):
        with self.assertRaises(ValueError):
          compact.validate(compact.Result(reviewed=reviewed,spans=[]),batch)
    self.assertEqual(compact.validate(compact.Result(reviewed=['B2','B1'],spans=[]),batch),[])

  def test_exact_quotes_known_blocks_and_valid_occurrences(self):
    batch=[{'id':'B1','text':'No fracture. No fracture.'}]
    for item in (span('no fracture'),span('No fracture',occurrence=3),span('No fracture',block_id='unknown')):
      with self.subTest(item=item.model_dump()):
        with self.assertRaises(ValueError):
          compact.validate(compact.Result(reviewed=['B1'],spans=[item]),batch)
    resolved=compact.validate(compact.Result(reviewed=['B1'],spans=[span('No fracture',occurrence=2)]),batch)
    self.assertEqual(resolved[0][1:],(13,24))

  def test_partial_numbers_rejected_but_repeated_real_values_allowed(self):
    for text,quote in [('100%','0%'),('100%','10'),('12345','234'),('100.0%','0%'),('100,0%','0%')]:
      with self.subTest(text=text,quote=quote):
        with self.assertRaisesRegex(ValueError,'part of a number'):
          compact.validate(compact.Result(reviewed=['B1'],spans=[span(quote)]),[{'id':'B1','text':text}])
    result=compact.validate(compact.Result(reviewed=['B1'],spans=[span('0%',occurrence=2)]),
      [{'id':'B1','text':'100%, then 0%.'}])
    self.assertEqual(result[0][1:],(11,13))

  def test_medical_quote_keeps_ordinary_date(self):
    text='No fracture on 29 avril 2021; ongoing pain.'
    ranges=compact.health_ranges(0,len(text),text,[])
    visible=''.join(text[a:b] for a,b in ranges)
    self.assertNotIn('29 avril 2021',visible)
    self.assertIn('No fracture',visible)
    self.assertIn('ongoing pain',visible)

  def test_birthday_and_explicit_secret_date_are_preserved(self):
    birthday='Born on 29 avril 2021; health assessment.'
    self.assertEqual(compact.health_ranges(0,len(birthday),birthday,[]),[(0,len(birthday))])
    text='No fracture on 29 avril 2021.'
    start=text.index('29 avril 2021')
    self.assertEqual(compact.health_ranges(0,len(text),text,[(start,start+13)]),[(0,len(text))])


class CompactCacheTests(unittest.TestCase):
  def test_repeat_session_uses_cache_with_zero_provider_tokens(self):
    text='Ordinary public context.'
    session=session_for(text)
    with patch.object(llm_review,'blocks_for',return_value=[block(text)]), patch.object(compact,'call',side_effect=answer) as call:
      first=compact.review(session)
      second=compact.review(session)
    self.assertEqual(call.call_count,1)
    self.assertEqual(first['usage']['input_tokens'],31)
    self.assertEqual(second['cached_batches'],1)
    self.assertTrue(all(value==0 for value in second['usage'].values()))
    self.assertNotIn('quality_cache',session.model_dump())

  def test_context_model_and_organisation_invalidate_cache(self):
    text='Ordinary public context.'
    for changed in ('role','goal','model','organisation','confidential_terms','retain_requests'):
      with self.subTest(changed=changed):
        session=session_for(text)
        with patch.object(llm_review,'blocks_for',return_value=[block(text)]), patch.object(compact,'call',side_effect=answer) as call:
          compact.review(session)
          if changed in ('role','goal'):
            setattr(session.context,changed,'Different authorised task')
            result=compact.review(session)
          elif changed in ('confidential_terms','retain_requests'):
            setattr(session.context,changed,['Alice Smith'])
            result=compact.review(session)
          elif changed=='organisation':
            session.organisation_id='different-org'
            result=compact.review(session)
          else:
            with patch.object(compact._config,'QUALITY_MODEL','different-model'):
              result=compact.review(session)
        self.assertEqual(call.call_count,2)
        self.assertEqual(result['cached_batches'],0)

  def test_invalid_batch_retry_does_not_commit_any_batch_cache(self):
    first='A'*9000
    second='B'*9000
    session=session_for(first+second)
    session.quality_cache={'unrelated':{'retained':True}}
    original=copy.deepcopy(session.quality_cache)
    calls=[]
    def provider(payload):
      name=payload['blocks'][0]['id']
      calls.append(name)
      if name=='B2':
        return compact.Result(reviewed=[],spans=[]),{'input_tokens':10}
      return answer(payload)
    with patch.object(llm_review,'blocks_for',return_value=[block(first),block(second,len(first),'B2')]), patch.object(compact,'call',side_effect=provider):
      with self.assertRaises(ValueError):
        compact.review(session)
    self.assertEqual(Counter(calls),Counter({'B1':1,'B2':2}))
    self.assertEqual(session.quality_cache,original)
    self.assertEqual(session.review.revision,1)

  def test_only_failed_batch_retried_and_usage_includes_repair(self):
    first='A'*9000
    second='B'*9000
    session=session_for(first+second)
    calls=[]
    def provider(payload):
      name=payload['blocks'][0]['id']
      calls.append(name)
      if name=='B2' and 'validation_feedback' not in payload:
        return compact.Result(reviewed=[],spans=[]),{'input_tokens':5,'output_tokens':2,'requests':1}
      return answer(payload)
    with patch.object(llm_review,'blocks_for',return_value=[block(first),block(second,len(first),'B2')]), patch.object(compact,'call',side_effect=provider):
      result=compact.review(session)
    self.assertEqual(Counter(calls),Counter({'B1':1,'B2':2}))
    self.assertEqual(result['usage']['input_tokens'],67)
    self.assertEqual(result['usage']['requests'],3)
    self.assertEqual(len(session.quality_cache),2)


class CompactHumanDecisionTests(unittest.TestCase):
  def test_services_preserve_confirmed_keep_and_remove_including_new_type(self):
    text='No fracture. Alice Smith.'
    findings=[]
    for fid,quote,selected,status,kind in [
        ('health','No fracture',True,'confirmed_remove','medical_information'),
        ('name','Alice Smith',False,'confirmed_keep','person_name')]:
      start=text.index(quote)
      findings.append(Finding(finding_id=fid,field_type=kind,original_text=quote,
        location=Location(page_number=1,start=start,end=start+len(quote)),
        sensitivity_levels=['personal-private'],subcategory='unit',detector='spacy/unit',
        reason='Unit fixture',selected=selected,review_status=status))
    session=session_for(text,findings)
    def provider(payload):
      # Omit the confirmed medical finding and try to hide the confirmed name with another type.
      return answer(payload,[span('Alice Smith',kind='medical_information')])
    original_engine=compact.review
    with patch.object(services.store,'get',return_value=session), patch.object(llm_review,'blocks_for',return_value=[block(text)]), patch.object(compact,'call',side_effect=provider), patch.object(llm_review,'review',side_effect=original_engine):
      result=services.quality_review('compact-unit',QualityRequest(revision=1))
    health=next(f for f in result.findings if f.finding_id=='health')
    name=next(f for f in result.findings if f.finding_id=='name')
    self.assertTrue(health.selected)
    self.assertEqual(health.review_status,'confirmed_remove')
    self.assertFalse(name.selected)
    self.assertEqual(name.review_status,'confirmed_keep')
    aliases=[f for f in result.findings if f.original_text=='Alice Smith']
    self.assertGreaterEqual(len(aliases),2)
    self.assertTrue(all(not f.selected and f.review_status=='confirmed_keep' for f in aliases))

  def test_detector_rerun_preserves_human_choices_even_if_type_changes_or_finding_disappears(self):
    text='No fracture. Alice Smith.'
    for missing in (False, True):
      with self.subTest(detector_misses_prior_span=missing):
        originals=[]
        for fid,quote,selected,status in [
            ('health','No fracture',True,'confirmed_remove'),
            ('name','Alice Smith',False,'confirmed_keep')]:
          start=text.index(quote)
          originals.append(Finding(finding_id=fid,field_type='other',original_text=quote,
            location=Location(page_number=1,start=start,end=start+len(quote)),
            sensitivity_levels=['personal-private'],subcategory='unit',detector='spacy/unit',
            reason='Reviewer decision',selected=selected,review_status=status))
        session=session_for(text,originals)
        regenerated=[] if missing else [f.model_copy(update={
          'finding_id':'new-'+f.finding_id, 'field_type':'medical_information',
          'selected':not f.selected, 'review_status':'unreviewed'}) for f in originals]
        with patch.object(services.store,'get',return_value=session), \
            patch.object(services.rules,'findings_for_page',side_effect=lambda *args,**kwargs:copy.deepcopy(regenerated)), \
            patch.object(services.memory,'for_screening',return_value=[]), \
            patch.object(services.layout,'annotate'):
          result=services.apply_predictions('compact-unit',Context(),[[]])
        for original in originals:
          matching=[f for f in result.findings if f.original_text==original.original_text]
          self.assertTrue(matching,'A confirmed span disappeared on detector rerun')
          self.assertTrue(all(f.selected==original.selected for f in matching))
          self.assertTrue(all(f.review_status==original.review_status for f in matching))
