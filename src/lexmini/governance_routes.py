# src/lexmini/governance_routes.py
"""Thin routes for the isolated synthetic governance walkthrough."""
from typing import Literal
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from .governance_demo import demo_store, PersonRole

router = APIRouter(prefix='/api/governance-demo', tags=['synthetic-demo'])


def bearer(authorization):
  if not authorization or not authorization.startswith('Bearer '):
    raise HTTPException(401, 'A demo session is required.')
  return authorization[7:]


class Input(BaseModel):
  model_config = ConfigDict(extra='forbid')


class Reveal(Input):
  document_id: str = Field(max_length=100)
  token: str = Field(max_length=100)


class Approval(Input):
  entity_id: str = Field(max_length=100)
  role: PersonRole
  reason: str = Field(min_length=1, max_length=500)
  clear_protection: bool = False


class GrantChange(Input):
  user_id: Literal['translator', 'personal', 'matter']
  action: Literal['grant', 'revoke', 'expire']
  expires_in: int = Field(default=300, ge=1, le=1800)


@router.post('/runs')
def create():
  return demo_store.create()


@router.post('/runs/{run_id}/sessions')
def sessions(run_id: str, authorization: str | None = Header(default=None)):
  return demo_store.sessions(run_id, bearer(authorization))


@router.get('/runs/{run_id}/state')
def state(run_id: str, authorization: str | None = Header(default=None)):
  return demo_store.state(run_id, bearer(authorization))


@router.get('/runs/{run_id}/documents/{document_id}')
def document(run_id: str, document_id: str, authorization: str | None = Header(default=None)):
  return demo_store.document(run_id, bearer(authorization), document_id)


@router.post('/runs/{run_id}/reveal')
def reveal(run_id: str, request: Reveal, authorization: str | None = Header(default=None)):
  return demo_store.reveal(run_id, bearer(authorization), request.document_id, request.token)


@router.post('/runs/{run_id}/classify')
def classify(run_id: str, request: Approval, authorization: str | None = Header(default=None)):
  return demo_store.classify(run_id, bearer(authorization), **request.model_dump())


@router.post('/runs/{run_id}/grant')
def grant(run_id: str, request: GrantChange, authorization: str | None = Header(default=None)):
  return demo_store.grant(run_id, bearer(authorization), **request.model_dump())
