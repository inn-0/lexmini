# src/lexmini/governance_demo.py
"""Executable governance demonstration, isolated from uploaded documents.

Use synthetic records and short-lived server-issued demo identities. Every reveal
checks current policy. This demonstrates authorisation, not production sign-in.
"""

import secrets
import threading
import time
from typing import Literal

from pydantic import BaseModel, Field

PersonRole = Literal["unknown", "lawyer", "judge", "client", "plaintiff", "opposing_party"]
LEVELS = {"public", "personal-private", "professional-secrecy"}
CAPABILITIES = {"translator": {"public"}, "personal": {"public", "personal-private"},
  "matter": LEVELS, "curator": LEVELS, "outsider": LEVELS}


class DemoDenied(Exception):
  def __init__(self, message: str, status: int = 403):
    self.message, self.status = message, status


class Person(BaseModel):
  id: str
  name: str
  roles: list[PersonRole]
  protected: bool = False


class Value(BaseModel):
  token: str
  value: str
  entity_id: str | None = None
  levels: list[str] = Field(default_factory=list)


class Grant(BaseModel):
  levels: list[str]
  expires_at: float
  revoked: bool = False


class Identity(BaseModel):
  user_id: str
  organisation_id: str
  expires_at: float


class Run(BaseModel):
  id: str
  organisation_id: str = "demo-firm-a"
  expires_at: float
  policy_version: int = 1
  people: dict[str, Person]
  values: dict[str, dict[str, Value]]
  grants: dict[str, Grant]
  sessions: dict[str, Identity] = Field(default_factory=dict)
  events: list[dict] = Field(default_factory=list)


class DemoStore:
  def __init__(self, clock=time.time):
    self.clock = clock
    self.lock = threading.RLock()
    self.runs: dict[str, Run] = {}

  def event(self, run, actor, action, **details):
    run.events.append({"sequence": (run.events[-1]["sequence"] + 1) if run.events else 1, "at": self.clock(),
      "actor": actor, "action": action, "policy_version": run.policy_version, **details})
    if len(run.events) > 1000:
      run.events = run.events[-1000:]

  def create(self):
    with self.lock:
      now = self.clock()
      self.runs = {k:r for k,r in self.runs.items() if r.expires_at > now}
      if len(self.runs) >= 20:
        raise DemoDenied("The demo has 20 active walkthroughs. Reuse an open walkthrough.",429)
      people = {"alice":Person(id="alice",name="Alice Example",roles=["lawyer"]),
        "billy":Person(id="billy",name="Billy Example",roles=["client"],protected=True)}
      values = {
        "[PARTY_00001]":Value(token="[PARTY_00001]",value="Alice Example",entity_id="alice"),
        "[PARTY_00002]":Value(token="[PARTY_00002]",value="Billy Example",entity_id="billy"),
        "[ADDRESS_00001]":Value(token="[ADDRESS_00001]",value="12 Fictional Lane",levels=["personal-private"]),
        "[TERM_00001]":Value(token="[TERM_00001]",value="Offer a confidential settlement of CHF 4,000.",levels=["professional-secrecy"])}
      run = Run(id=secrets.token_urlsafe(18),expires_at=now+7200,people=people,
        values={"earlier-case":values,"later-intake":{"[PARTY_00001]":values["[PARTY_00001]"].model_copy(deep=True)}},
        grants={u:Grant(levels=sorted(CAPABILITIES[u]),expires_at=now+1800) for u in CAPABILITIES})
      self.runs[run.id] = run
      session = self.issue(run,"curator")
      self.event(run,"system","synthetic_walkthrough_created")
      return {"run_id":run.id,"session":session,"expires_at":run.expires_at,
        "notice":"Synthetic data. This console issues demo identities; production sign-in is not connected."}

  def issue(self, run, user_id):
    if user_id not in CAPABILITIES:
      raise DemoDenied("Unknown demo identity",400)
    token = secrets.token_urlsafe(32)
    run.sessions[token] = Identity(user_id=user_id,
      organisation_id="demo-firm-b" if user_id == "outsider" else run.organisation_id,
      expires_at=min(self.clock()+1800,run.expires_at))
    return token

  def identity(self, run_id, token):
    run = self.runs.get(run_id)
    if not run or run.expires_at <= self.clock():
      raise DemoDenied("Demo walkthrough expired. Start a new walkthrough.",404)
    identity = run.sessions.get(token)
    if not identity or identity.expires_at <= self.clock():
      raise DemoDenied("A current demo session is required.",401)
    return run,identity

  def curator(self, run_id, token):
    run, actor = self.identity(run_id,token)
    if actor.user_id != "curator" or actor.organisation_id != run.organisation_id:
      raise DemoDenied("Only the demo curator can change policy.")
    return run,actor

  def sessions(self, run_id, token):
    with self.lock:
      run,actor = self.curator(run_id,token)
      return {u:self.issue(run,u) for u in ["translator","personal","matter","outsider"]}

  def levels(self, run, value):
    if not value.entity_id:
      return set(value.levels)
    person = run.people[value.entity_id]
    if person.protected or "unknown" in person.roles:
      return {"personal-private","professional-secrecy"}
    return {"public"}

  def document(self, run_id, token, document_id="earlier-case"):
    with self.lock:
      run,actor = self.identity(run_id,token)
      if actor.organisation_id != run.organisation_id:
        raise DemoDenied("This document belongs to another organisation.")
      if document_id not in run.values:
        raise DemoDenied("Unknown demo document",404)
      # The intake is visible to the curator only; it has not been shared.
      if document_id == "later-intake" and actor.user_id != "curator":
        raise DemoDenied("No assignment to this intake document.")
      return {"document_id":document_id,"user_id":actor.user_id,"policy_version":run.policy_version,
        "fields":[{"token":v.token,"levels":sorted(self.levels(run,v))} for v in run.values[document_id].values()],
        "text":"Counsel: [PARTY_00001]. Client: [PARTY_00002]. Address: [ADDRESS_00001]. Strategy: [TERM_00001]." if document_id == "earlier-case" else "New client intake: [PARTY_00001]."}

  def reveal(self, run_id, token, document_id, value_token):
    with self.lock:
      run,actor = self.identity(run_id,token)
      reason = None
      value = run.values.get(document_id,{}).get(value_token)
      grant = run.grants.get(actor.user_id)
      if actor.organisation_id != run.organisation_id:
        reason = "Another organisation cannot reveal this document."
      elif document_id != "earlier-case" and actor.user_id != "curator":
        reason = "No assignment to this document."
      elif value is None:
        reason = "Unknown token in this document."
      elif not grant or grant.revoked:
        reason = "Reveal grant revoked."
      elif grant.expires_at <= self.clock():
        reason = "Reveal grant expired."
      elif not self.levels(run,value) <= (set(grant.levels) & CAPABILITIES[actor.user_id]):
        reason = "Current permissions do not cover every protection level on this value."
      self.event(run,actor.user_id,"reveal_denied" if reason else "reveal_allowed",document_id=document_id,token=value_token,reason=reason)
      if reason:
        raise DemoDenied(reason)
      return {"token":value.token,"value":value.value,"policy_version":run.policy_version}

  def classify(self, run_id, token, entity_id, role, reason, clear_protection=False):
    with self.lock:
      run,actor = self.curator(run_id,token)
      if entity_id not in run.people or role not in {"unknown","lawyer","judge","client","plaintiff","opposing_party"}:
        raise DemoDenied("Unknown person or role",400)
      if not reason.strip():
        raise DemoDenied("Record why this role was approved or corrected.",400)
      person = run.people[entity_id]
      if clear_protection:
        if role not in {"lawyer","judge"}:
          raise DemoDenied("A correction must specify the reviewed non-client role.",400)
        person.roles = [role]
        person.protected = False
      else:
        if role not in person.roles:
          person.roles.append(role)
        if role in {"client","plaintiff","opposing_party"}:
          person.protected = True
      run.policy_version += 1
      self.event(run,actor.user_id,"protection_corrected" if clear_protection else "person_role_approved",
        entity_id=entity_id,role=role,reason=reason)
      return self.state(run_id,token)

  def grant(self, run_id, token, user_id, action, expires_in=300):
    with self.lock:
      run,actor = self.curator(run_id,token)
      if user_id not in {"translator","personal","matter"} or action not in {"grant","revoke","expire"}:
        raise DemoDenied("Unknown demo grant action",400)
      grant = run.grants[user_id]
      if action == "grant":
        grant.revoked = False
        grant.expires_at = self.clock()+min(max(expires_in,1),1800)
      elif action == "expire":
        grant.expires_at = self.clock()
      else:
        grant.revoked = True
      run.policy_version += 1
      self.event(run,actor.user_id,"grant_"+action,user_id=user_id,expires_at=grant.expires_at)
      return self.state(run_id,token)

  def state(self, run_id, token):
    with self.lock:
      run,actor = self.curator(run_id,token)
      return {"policy_version":run.policy_version,"people":[p.model_dump() for p in run.people.values()],
        "grants":{u:g.model_dump() for u,g in run.grants.items() if u not in {"curator","outsider"}},
        "events":run.events[-30:],"server_time":self.clock()}


demo_store = DemoStore()
