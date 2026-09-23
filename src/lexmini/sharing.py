# src/lexmini/sharing.py
"""Real-document, expiring recipient downloads for the trusted local prototype.

Anyone with the curator UI can issue/revoke. Recipient links are bearer grants,
not verified identities. Check each download; never send the private key map.
"""
import secrets
import time
import threading
from pydantic import BaseModel, ConfigDict, Field
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from . import services
from .schemas import ExportRequest

router=APIRouter()
_lock=threading.RLock()
_grants={}
_audit=[]


class ShareRequest(BaseModel):
  model_config=ConfigDict(extra='forbid')
  revision:int
  recipient:str=Field(min_length=1,max_length=100)
  selected_ids:list[str]=Field(max_length=10000)
  reveal_ids:list[str]=Field(default_factory=list,max_length=10000)
  expires_in:int=Field(default=60,ge=1,le=3600)


def event(action,document_id,**fields):
  _audit.append({'at':time.time(),'action':action,'document_id':document_id,**fields})
  if len(_audit)>1000:del _audit[:-1000]


@router.post('/api/documents/{document_id}/share')
def issue(document_id:str,request:ShareRequest):
  session=services.store.get(document_id)
  with session.lock,_lock:
    if not session.review.analysed or request.revision!=session.review.revision:
      raise HTTPException(409,'Review version changed. Create a fresh grant.')
    ids={f.finding_id for f in session.review.findings}
    if (set(request.selected_ids)|set(request.reveal_ids))-ids:
      raise HTTPException(400,'Unknown finding in share permissions')
    for key,grant in list(_grants.items()):
      if grant['expires_at']<=time.time():del _grants[key]
    if len(_grants)>=100:raise HTTPException(429,'Too many active share grants')
    token=secrets.token_urlsafe(32)
    for grant in _grants.values():
      if grant['document_id']==document_id and grant['recipient']==request.recipient and not grant['revoked']:
        grant['revoked']=True
        event('replaced_grant_revoked',document_id,recipient=request.recipient)
    _grants[token]={'document_id':document_id,'revision':request.revision,'recipient':request.recipient,
      'selected_ids':sorted(set(request.selected_ids)-set(request.reveal_ids)),
      'reveal_ids':request.reveal_ids,'expires_at':time.time()+request.expires_in,'revoked':False}
    event('grant_issued',document_id,recipient=request.recipient,expires_in=request.expires_in,reveal_ids=request.reveal_ids)
    return {'token':token,'url':'/api/shared/'+token+'/pdf','expires_at':_grants[token]['expires_at'],
      'notice':'Prototype bearer link. Whoever has this link can download this approved copy until expiry or revocation.'}


@router.post('/api/documents/{document_id}/share/{token}/revoke')
def revoke(document_id:str,token:str):
  services.store.get(document_id)
  with _lock:
    grant=_grants.get(token)
    if not grant or grant['document_id']!=document_id:raise HTTPException(404,'Grant not found')
    grant['revoked']=True
    event('grant_revoked',document_id,recipient=grant['recipient'])
    return {'revoked':True}


@router.get('/api/documents/{document_id}/share-audit')
def audit(document_id:str):
  services.store.get(document_id)
  with _lock:return [e for e in _audit if e['document_id']==document_id]


@router.get('/api/shared/{token}/pdf')
def download(token:str):
  # Release grant lock before taking the document lock to avoid lock inversion.
  with _lock:grant=_grants.get(token)
  if not grant:raise HTTPException(404,'Share link expired or not found')
  session=services.store.get(grant['document_id'])
  with session.lock,_lock:
    if grant['revoked'] or grant['expires_at']<=time.time():
      event('download_denied',grant['document_id'],recipient=grant['recipient'],reason='expired_or_revoked')
      raise HTTPException(403,'This share grant expired or was revoked')
    if session.review.revision!=grant['revision']:
      raise HTTPException(403,'The approved document version changed; a new grant is required')
    payload=services.export(grant['document_id'],ExportRequest(revision=grant['revision'],
      selected_ids=grant['selected_ids'],format='pdf',pdf_layout='reflow'))
    event('download_allowed',grant['document_id'],recipient=grant['recipient'],revision=grant['revision'])
    return Response(payload,media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="lexmini-recipient.pdf"'})
