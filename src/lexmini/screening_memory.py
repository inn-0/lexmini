# src/lexmini/screening_memory.py
"""Private single-workspace prototype memory, not a hosted authorisation system.

Only explicit reviewer actions add terms. Keep files out of source control and
API responses. A future database adapter must resolve scope from authenticated
assignments, not trust this local review-set selector as an access boundary.
"""

import json
import os
import secrets
import threading
from datetime import datetime, timezone
from typing import Literal
from pathlib import Path as pPath

from pydantic import BaseModel, Field

from . import _config
from .matching import key
from .schemas import FieldType, Sensitivity


class MemoryTerm(BaseModel):
  id: str
  text: str = Field(min_length=2, max_length=200)
  field_type: FieldType
  sensitivity_levels: list[Sensitivity]
  review_set: str
  origin_document_hash: str
  organisation_id: str = "local-organisation"
  approval_state: Literal["candidate", "approved"] = "approved"
  approved_at: str | None = None
  approved_by: str = "local-reviewer"


class ScreeningMemory:
  def __init__(self, path: pPath):
    self.path = path
    self.lock = threading.RLock()

  def _read(self):
    if not self.path.exists():
      return []
    try:
      data = json.loads(self.path.read_text())
      if data.get("version") not in {1, 2}:
        raise ValueError("Unsupported version")
      if data["version"] == 2 and any(not {"organisation_id", "approval_state"} <= item.keys() for item in data["terms"]):
        raise ValueError("Missing organisation or approval state")
      return [MemoryTerm.model_validate(item) for item in data["terms"]]
    except (ValueError, TypeError, KeyError, AttributeError):
      # Validation errors can otherwise echo the protected record's contents.
      raise ValueError("The private screening memory could not be read. Check its format locally.") from None

  def _write(self, terms):
    self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = self.path.with_name(self.path.name + "." + secrets.token_hex(8))
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
      with os.fdopen(descriptor, "w") as stream:
        json.dump({"version": 2, "terms": [t.model_dump() for t in terms]}, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
      os.replace(temporary, self.path)
    finally:
      temporary.unlink(missing_ok=True)

  def for_screening(self, review_set: str, *, organisation_id: str = "local-organisation"):
    with self.lock:
      return [t for t in self._read() if t.organisation_id == organisation_id
        and t.approval_state == "approved" and t.review_set in {review_set, "*"}]

  def remember(self, *, text, field_type, sensitivity_levels, review_set, origin_document_hash,
    organisation_id="local-organisation", approval_state="approved", approved_at=None, approved_by="local-reviewer"):
    if approval_state != "approved":
      raise ValueError("Only explicitly approved terms can be saved")
    with self.lock:
      terms = self._read()
      existing = next((t for t in terms if t.organisation_id == organisation_id
        and key(t.text) == key(text) and t.field_type == field_type and t.review_set == review_set), None)
      if existing:
        existing.sensitivity_levels = list(dict.fromkeys([*existing.sensitivity_levels, *sensitivity_levels]))
      else:
        if sum(t.organisation_id == organisation_id for t in terms) >= 500:
          raise ValueError("The prototype memory limit is 500 terms per organisation")
        existing = MemoryTerm(id=secrets.token_urlsafe(20), text=text, field_type=field_type,
          sensitivity_levels=sensitivity_levels, review_set=review_set, origin_document_hash=origin_document_hash,
          organisation_id=organisation_id)
        terms.append(existing)
      existing.approval_state = "approved"
      existing.approved_at = datetime.now(timezone.utc).isoformat()
      existing.approved_by = approved_by
      self._write(terms)


memory = ScreeningMemory(_config.ROOT / ".runtime/screening_memory.json")
