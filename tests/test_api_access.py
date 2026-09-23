# tests/test_api_access.py
"""Check the fixed deadline without spending tokens or requiring credentials."""
import asyncio
import unittest
from datetime import timedelta
from unittest.mock import patch
from lexmini import api_access, llm_review


class ApiAccessTests(unittest.TestCase):
  def test_before_deadline(self):
    with patch('lexmini.api_access.datetime') as clock:
      clock.now.return_value=api_access.OPENAI_EXPIRES_AT-timedelta(microseconds=1)
      api_access.require_openai_access()

  def test_at_and_after_deadline(self):
    for delta in [timedelta(),timedelta(days=1)]:
      with patch('lexmini.api_access.datetime') as clock:
        clock.now.return_value=api_access.OPENAI_EXPIRES_AT+delta
        with self.assertRaisesRegex(ValueError,'expired'):
          api_access.require_openai_access()
        with self.assertRaisesRegex(ValueError,'expired'):
          asyncio.run(api_access.guard_openai_request(None))

  def test_expired_call_stops_before_client_creation(self):
    with patch('lexmini.api_access.datetime') as clock, patch('openai.AsyncOpenAI') as client:
      clock.now.return_value=api_access.OPENAI_EXPIRES_AT
      with self.assertRaisesRegex(ValueError,'expired'):
        llm_review.call({})
      client.assert_not_called()
