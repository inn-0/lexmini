# tests/test_quality_transport.py
# Rationale: verify that the provider request cannot inherit Fast processing.
# Assumptions: the Responses API returns the configured structured result.
# Constraints: mock the HTTP transport; never send document text or spend API credit.
import json
import unittest
from unittest.mock import patch

import httpx
from openai import AsyncOpenAI
from lexmini import llm_review


class QualityTransportTests(unittest.TestCase):
  def test_standard_reasoning_request(self):
    requests = []
    def respond(request):
      requests.append(json.loads(request.content))
      output = {'suggested_role':'Translator', 'suggested_goal':'Protect private facts',
        'changes':[], 'additions':[]}
      return httpx.Response(200, json={
        'id':'resp_test', 'object':'response', 'created_at':1, 'model':'gpt-6-sol',
        'status':'completed', 'service_tier':'default',
        'output':[{'type':'message', 'id':'msg_test', 'role':'assistant',
          'status':'completed', 'content':[{'type':'output_text',
            'text':json.dumps(output), 'annotations':[]}]}],
        'usage':{'input_tokens':10, 'output_tokens':10, 'total_tokens':20}})
    client = AsyncOpenAI(api_key='test-only', http_client=httpx.AsyncClient(
      transport=httpx.MockTransport(respond)))
    with patch('openai.AsyncOpenAI', return_value=client), \
        patch('lexmini._config.API_KEY_OPENAI', 'test-only'), \
        patch('lexmini.api_access.require_openai_access'):
      result, usage = llm_review.call({'blocks':[]}, 'gpt-6-sol')
    self.assertEqual(requests[0]['service_tier'], 'default')
    self.assertEqual(requests[0]['reasoning']['effort'], 'medium')
    self.assertFalse(requests[0]['store'])
    self.assertNotIn('temperature', requests[0])
    self.assertEqual(result.changes, [])
    self.assertEqual(usage['input_tokens'], 10)
