# src/lexmini/quality.py
"""Replay explicitly saved public examples, never cache uploaded client files.

Verify PDF and extracted-page hashes before using model offsets. Reapply current
rules and local spaCy; never issue a remote inference call for cache replay.
"""

import hashlib
import json

from . import _config, services, layout
from .schemas import Context


def catalogue():
  items = []
  for path in sorted((_config.ROOT / "data/quality").glob("*.baseline.json")):
    data = json.loads(path.read_text())
    items.append({"id": path.name.removesuffix(".baseline.json"),
      "title": path.name.removesuffix(".baseline.json"), "pages": len(data["pages"]),
      "model": data["model"]["name"]})
  return items


def load(sample_id: str, context: Context):
  if sample_id not in {item["id"] for item in catalogue()}:
    raise KeyError("Cached example not found")
  record = json.loads((_config.ROOT / "data/quality" / f"{sample_id}.baseline.json").read_text())
  if record["schema_version"] != 1:
    raise ValueError("Unsupported quality cache version")
  source = (_config.ROOT / record["pdf_path"]).resolve()
  if not source.is_relative_to((_config.ROOT / "data/reference").resolve()):
    raise ValueError("Quality examples must refer to public reference data")
  payload = source.read_bytes()
  if hashlib.sha256(payload).hexdigest() != record["pdf_sha256"]:
    raise ValueError("The PDF has changed since the saved model run")
  review = services.store.create(payload, source.name)
  try:
    session = services.store.get(review.document_id)
    if len(session.extracted.pages) != len(record["pages"]):
      raise ValueError("The page count has changed since the saved model run")
    for page, cached in zip(session.extracted.pages, record["pages"]):
      if hashlib.sha256(page.text.encode()).hexdigest() != cached["text_sha256"]:
        raise ValueError("The extracted text has changed; model offsets cannot be replayed")
    screened = json.loads((_config.ROOT / "data/quality" / f"{sample_id}.screening.json").read_text())
    if screened["schema_version"] != 1 or screened["pdf_sha256"] != record["pdf_sha256"]:
      raise ValueError("Screening cache does not match the public PDF")
    if screened["text_hashes"] != [page["text_sha256"] for page in record["pages"]]:
      raise ValueError("Screening cache text positions differ from this PDF")
    if len(screened["spacy_spans"]) != len(session.extracted.pages):
      raise ValueError("Screening cache does not contain every page")
    context = context.model_copy(update={"languages": screened["languages"]})
    session.spacy_spans = screened["spacy_spans"]
    session.layout_regions = [layout.LayoutRegion.model_validate(r) for r in screened["regions"]]
    session.review.processing = "Cached " + screened["engine"]
    result = services.apply_predictions(review.document_id, context, [p["spans"] for p in record["pages"]] if context.use_privacy_filter else [[] for _ in record["pages"]])
    note = "Quality check: saved spaCy and Docling, with current rules. No model inference or paid API call. Privacy Filter candidates are included when that option is selected. Run OpenAI quality check separately to update decisions."
    session.review.warnings.append(note)
    result.warnings.append(note)
    return result
  except Exception:
    services.store.remove(review.document_id)
    raise
