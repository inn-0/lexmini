# tests/test_governance_demo.py
"""Policy changes must govern existing sessions and previously shared tokens."""
import json
import unittest
from fastapi.testclient import TestClient
from lexmini.governance_demo import DemoStore, DemoDenied
from lexmini.main import app


class GovernanceTests(unittest.TestCase):
  def setUp(self):
    self.now = [1000.0]
    self.store = DemoStore(clock=lambda:self.now[0])
    created = self.store.create()
    self.run, self.admin = created['run_id'], created['session']
    self.sessions = self.store.sessions(self.run, self.admin)

  def reveal(self, user, token='[PARTY_00001]'):
    return self.store.reveal(self.run, self.sessions[user], 'earlier-case', token)

  def test_no_originals_in_document(self):
    text = json.dumps(self.store.document(self.run, self.sessions['translator']))
    for original in ['Alice Example', 'Billy Example', '12 Fictional Lane', 'CHF 4,000']:
      self.assertNotIn(original, text)

  def test_permissions_require_every_category(self):
    self.assertEqual(self.reveal('translator')['value'], 'Alice Example')
    with self.assertRaises(DemoDenied): self.reveal('translator', '[PARTY_00002]')
    self.reveal('personal', '[ADDRESS_00001]')
    with self.assertRaises(DemoDenied): self.reveal('personal', '[TERM_00001]')
    with self.assertRaises(DemoDenied): self.reveal('personal', '[PARTY_00002]')
    self.reveal('matter', '[PARTY_00002]')
    self.reveal('matter', '[TERM_00001]')

  def test_approved_client_changes_old_document_and_session(self):
    self.reveal('translator')
    self.store.classify(self.run, self.admin, 'alice', 'client', 'Reviewed intake')
    with self.assertRaises(DemoDenied): self.reveal('translator')
    self.store.classify(self.run, self.admin, 'alice', 'lawyer', 'Also counsel')
    with self.assertRaises(DemoDenied): self.reveal('translator')
    self.store.classify(self.run, self.admin, 'alice', 'lawyer', 'Mistaken identity corrected', True)
    self.reveal('translator')

  def test_revoke_expire_and_reissue_existing_session(self):
    self.reveal('matter')
    self.store.grant(self.run, self.admin, 'matter', 'revoke')
    with self.assertRaises(DemoDenied): self.reveal('matter')
    self.store.grant(self.run, self.admin, 'matter', 'grant', 10)
    self.reveal('matter')
    self.now[0] += 11
    with self.assertRaises(DemoDenied): self.reveal('matter')
    self.store.grant(self.run, self.admin, 'matter', 'grant', 60)
    self.reveal('matter')
    self.store.grant(self.run, self.admin, 'matter', 'expire')
    with self.assertRaises(DemoDenied): self.reveal('matter')

  def test_organisation_and_curator_boundaries(self):
    with self.assertRaises(DemoDenied): self.reveal('outsider')
    with self.assertRaises(DemoDenied): self.store.state(self.run, self.sessions['matter'])
    with self.assertRaises(DemoDenied): self.store.classify(self.run, self.sessions['matter'], 'alice', 'client', 'Attempt')
    with self.assertRaises(DemoDenied): self.store.document(self.run, self.sessions['matter'], 'later-intake')

  def test_audit_excludes_revealed_values(self):
    self.reveal('matter', '[PARTY_00002]')
    with self.assertRaises(DemoDenied): self.reveal('translator', '[PARTY_00002]')
    audit = json.dumps(self.store.state(self.run, self.admin)['events'])
    self.assertIn('reveal_allowed', audit)
    self.assertIn('reveal_denied', audit)
    self.assertNotIn('Billy Example', audit)

  def test_unfinished_walkthrough_is_not_exposed(self):
    with TestClient(app) as client:
      response=client.post('/api/governance-demo/runs', headers={'X-Lexmini-Client':'review'},json={})
      self.assertEqual(response.status_code,404)
      self.assertEqual(client.get('/assets/governance-demo.html').status_code,404)


if __name__ == '__main__':
  unittest.main()
