# src/lexmini/services.py
"""Bounded in-memory documents, private Modal inference and reviewed exports."""

import secrets
import hashlib
import threading
import time
from typing import Any

import logfire
import modal
from pydantic import BaseModel, ConfigDict, Field

from . import _config, pdf, rules, spacy_detector, layout
from .schemas import Context, DocumentReview, ExportRequest, LearnRequest
from .matching import find_matches, key, prepare
from .screening_memory import MemoryTerm, memory
from .tokens import TokenRegistry, replace_pages, reflow_pdf


class Session(BaseModel):
  model_config = ConfigDict(arbitrary_types_allowed=True)
  payload: bytes
  extracted: pdf.ExtractedPDF
  review: DocumentReview
  expires: float
  lock: Any = Field(default_factory=threading.RLock, exclude=True)
  tokens: TokenRegistry = Field(default_factory=TokenRegistry)
  context: Context = Field(default_factory=Context)
  predictions: list[list[dict]] = Field(default_factory=list)
  examples: list[MemoryTerm] = Field(default_factory=list)
  spacy_spans: list[list[dict]] = Field(default_factory=list)
  layout_regions: list[layout.LayoutRegion] = Field(default_factory=list)
  organisation_id: str = _config.ORGANISATION_ID


class Store:
  def __init__(self):
    self.sessions: dict[str, Session] = {}
    self.lock = threading.RLock()

  def cleanup(self):
    with self.lock:
      for key, session in list(self.sessions.items()):
        if session.expires < time.monotonic():
          del self.sessions[key]

  def get(self, document_id: str) -> Session:
    self.cleanup()
    with self.lock:
      if document_id not in self.sessions:
        raise KeyError("Document expired or was closed. Open the PDF again.")
      session = self.sessions[document_id]
      session.expires = time.monotonic() + _config.SESSION_SECONDS
      return session

  def create(self, payload: bytes, filename: str) -> DocumentReview:
    if len(payload) > _config.MAX_BYTES:
      raise ValueError("Choose a PDF smaller than 20 MiB")
    extracted = pdf.extract(payload)
    document_id = secrets.token_urlsafe(24)
    review = DocumentReview(document_id=document_id, filename=filename[:250],
      page_count=len(extracted.pages), metadata_fields=list(extracted.metadata),
      warnings=extracted.warnings, pages=[p.info for p in extracted.pages], organisation_id=_config.ORGANISATION_ID)
    self.cleanup()
    with self.lock:
      if len(self.sessions) >= _config.MAX_SESSIONS:
        raise ValueError("Close another document first; this prototype holds up to eight documents")
      self.sessions[document_id] = Session(payload=payload, extracted=extracted, review=review,
        expires=time.monotonic() + _config.SESSION_SECONDS, organisation_id=review.organisation_id)
    return review.model_copy(deep=True)

  def remove(self, document_id: str):
    with self.lock:
      self.sessions.pop(document_id, None)


store = Store()


def screen_remote(texts: list[str], languages: list[str], payload: bytes) -> dict:
  worker = modal.Cls.from_name(_config.SCREENING_APP, _config.SCREENING_CLASS)()
  return worker.screen.spawn(texts, languages, payload).get(timeout=900)


def analyse(document_id: str, context: Context) -> DocumentReview:
  session = store.get(document_id)
  with session.lock:
    with logfire.span("Detect document fields", page_count=len(session.extracted.pages)):
      texts = [p.text for p in session.extracted.pages]
      payload = session.payload if context.use_layout else b""
      screened = screen_remote(texts, context.languages, payload)
      if screened["text_hashes"] != [hashlib.sha256(t.encode()).hexdigest() for t in texts]:
        raise ValueError("Screening text hashes differ from this document")
      if screened["pdf_sha256"] != (hashlib.sha256(payload).hexdigest() if payload else None):
        raise ValueError("Layout PDF hash differs from this document")
      supplements = screened["spacy_spans"]
      if len(supplements) != len(texts):
        raise ValueError("Screening did not return every page")
      regions = [layout.LayoutRegion.model_validate(r) for r in screened["regions"]]
      for page, spans_for_page in zip(session.extracted.pages, supplements):
        for span in spans_for_page:
          if not 0 <= span["start"] < span["end"] <= len(page.text):
            raise ValueError("Screening span is outside the page")
      session.spacy_spans, session.layout_regions = supplements, regions
      session.review.processing = screened["engine"]
      spans = [[] for _ in texts]
      if context.use_privacy_filter:
        worker = modal.Cls.from_name(_config.MODAL_APP, _config.MODAL_CLASS)()
        spans = worker.detect.spawn(texts).get(timeout=900)
        session.review.processing += ' + OpenAI Privacy Filter on Modal' 
    result = apply_predictions(document_id, context, spans)
    session.review.warnings = [w for w in session.review.warnings if not w.startswith("Quality check:")]
    result.warnings = list(session.review.warnings)
    if context.use_llm_review:
      from .schemas import QualityRequest
      try:
        return quality_review(document_id,QualityRequest(revision=result.revision))
      except ValueError as exc:
        session.review.warnings.append(str(exc))
        return session.review.model_copy(deep=True)
    return result


def apply_predictions(document_id: str, context: Context, spans: list[list[dict]]) -> DocumentReview:
  session = store.get(document_id)
  with session.lock:
    if len(spans) != len(session.extracted.pages):
      raise ValueError("The model did not return every page. No result was applied.")
    # Validate model offsets before allowing any prediction to seed repeat matching.
    initial = []
    supplements = session.spacy_spans or [[] for _ in session.extracted.pages]
    for page, predictions, supplement in zip(session.extracted.pages, spans, supplements):
      initial.extend(rules.findings_for_page(document_id, page, predictions, context, supplement, session.layout_regions))
    layout.annotate(initial, session.extracted.pages, session.layout_regions)
    document_seeds = {}
    for finding in initial:
      if finding.review_signal != "weak" and ("openai/privacy-filter" in finding.detector or "spacy/" in finding.detector) and 3 <= len(finding.original_text) <= 200:
        document_seeds[(key(finding.original_text), finding.field_type)] = MemoryTerm(
          id="document", text=finding.original_text, field_type=finding.field_type,
          sensitivity_levels=finding.sensitivity_levels, review_set=context.review_set, origin_document_hash="")
    sources = [(term, "document-repeat") for term in document_seeds.values()]
    sources += [(term, "reviewer-example") for term in session.examples]
    sources += [(term, "screening-memory") for term in memory.for_screening(context.review_set, organisation_id=session.organisation_id) if term.field_type in {"person_name", "organisation_name"}]
    findings = []
    for page, predictions, supplement in zip(session.extracted.pages, spans, supplements):
      extra = list(supplement)
      prepared = prepare(page.text)
      for term, source in sources:
        for start, end, kind in find_matches(page.text, term.text, term.field_type, context.fuzzy_matching, prepared):
          reason = "Repeated text matched a candidate elsewhere in this document; review before removing."
          if source != "document-repeat":
            reason = "Matches a reviewer-confirmed screening example. Only the text in this document is shown."
          if kind == "fuzzy":
            reason = "Approximate screening match (one character edit). Check the highlighted text; it may be a different entity."
          for level in term.sensitivity_levels:
            extra.append(dict(start=start, end=end, field_type=term.field_type, level=level,
              subcategory="screening_match", detector=source + ("-fuzzy" if kind == "fuzzy" else ""), reason=reason))
      findings.extend(rules.findings_for_page(document_id, page, predictions, context, extra, session.layout_regions))
    for finding in findings:
      finding.replacement = session.tokens.assign(finding.field_type, finding.original_text)
    layout.annotate(findings, session.extracted.pages, session.layout_regions)
    session.review.findings = findings
    session.context = context.model_copy(deep=True)
    session.review.review_set = context.review_set
    session.review.languages = list(context.languages)
    session.predictions = spans
    session.review.analysed = True
    session.review.revision += 1
    session.expires = time.monotonic() + _config.SESSION_SECONDS
    return session.review.model_copy(deep=True)


def learn(document_id: str, request: LearnRequest) -> DocumentReview:
  session = store.get(document_id)
  with session.lock:
    if not session.review.analysed:
      raise ValueError("Run detection before adding screening examples")
    if request.revision != session.review.revision:
      raise ValueError("Review changed. Refresh before adding an example.")
    current = {f.finding_id: f for f in session.review.findings}
    if set(request.kept_ids) - current.keys():
      raise ValueError("Unknown finding in the kept selection")
    if request.finding_id:
      if request.finding_id not in current:
        raise ValueError("Choose a finding in this document")
      chosen = current[request.finding_id]
      text, field_type, levels = chosen.original_text, chosen.field_type, chosen.sensitivity_levels
    else:
      text, field_type, levels = request.text.strip(), request.field_type, request.sensitivity_levels
    if not 2 <= len(text) <= 200 or "public" in levels:
      raise ValueError("Choose a protected term between 2 and 200 characters")
    if not any(find_matches(page.text, text, field_type, fuzzy=False) for page in session.extracted.pages):
      raise ValueError("The example must occur in the open document. Copy its exact text.")
    term = MemoryTerm(id=secrets.token_urlsafe(12), text=text, field_type=field_type,
      sensitivity_levels=levels, review_set="*" if request.workspace_wide else session.context.review_set,
      origin_document_hash=hashlib.sha256(session.payload).hexdigest(), organisation_id=session.organisation_id)
    if request.remember and field_type not in {"person_name", "organisation_name"}:
      raise ValueError("Only approved people and organisations are remembered across documents. Apply other terms to this document only.")
    if len(session.examples) >= 100:
      raise ValueError("This document already has 100 manual examples")
    old_review = session.review.model_copy(deep=True)
    old_tokens = session.tokens.model_copy(deep=True)
    old_examples = list(session.examples)
    try:
      session.examples.append(term)
      predictions = session.predictions or [[] for _ in session.extracted.pages]
      apply_predictions(document_id, session.context, predictions)
      if request.remember:
        memory.remember(**term.model_dump(exclude={"id"}))
    except Exception:
      session.review, session.tokens, session.examples = old_review, old_tokens, old_examples
      raise
    quality_by_id={f.finding_id:f for f in old_review.findings if 'openai-quality' in f.detector}
    existing_ids={f.finding_id for f in session.review.findings}
    for finding in session.review.findings:
      if finding.finding_id in quality_by_id:
        prior=quality_by_id[finding.finding_id]
        for field in ['field_type','selected','context_suggestion','context_reason','reason','detector','sensitivity_levels','legal_reference','replacement']:
          setattr(finding,field,getattr(prior,field))
    session.review.findings.extend(f.model_copy(deep=True) for fid,f in quality_by_id.items() if fid not in existing_ids)
    session.review.quality_check=old_review.quality_check
    for finding in session.review.findings:
      if finding.finding_id in request.kept_ids and finding.finding_id != request.finding_id:
        finding.selected = False
        finding.review_status = "confirmed_keep"
      if key(finding.original_text) == key(text) and finding.field_type == field_type:
        finding.selected = True
        finding.review_status = "confirmed_remove"
    return session.review.model_copy(deep=True)


def export(document_id: str, request: ExportRequest) -> bytes:
  session = store.get(document_id)
  with session.lock:
    if not session.review.analysed:
      raise ValueError("Run detection before exporting")
    if request.revision != session.review.revision:
      raise ValueError("Detection results changed. Refresh the review before exporting.")
    if not all(page.info.readable for page in session.extracted.pages):
      raise ValueError("This PDF has unreadable pages. OCR is needed before export.")
    by_id = {f.finding_id: f for f in session.review.findings}
    if set(request.selected_ids) - by_id.keys():
      raise ValueError("The selection contains an unknown finding")
    selected = [by_id[key] for key in set(request.selected_ids)]
    if request.format == "pdf" and request.pdf_layout == "original":
      return pdf.export_pdf(session.payload, selected)
    pages = replace_pages(session.extracted.pages, selected, session.tokens, request.replacement_style)
    if request.format == "pdf":
      return reflow_pdf(pages)
    return "\n\n".join(pages).encode("utf-8")


def restore_review(document_id, request):
  """Restore a curator's tab-local review; never trust supplied PDF coordinates."""
  session = store.get(document_id)
  with session.lock:
    if session.review.analysed:
      raise ValueError("Restore only into a newly opened document")
    restored = []
    ids = set()
    for supplied in request.findings:
      location = supplied.location
      if location.source != "page_text" or location.page_number is None or not 1 <= location.page_number <= len(session.extracted.pages):
        raise ValueError("Restored finding has an invalid page")
      page = session.extracted.pages[location.page_number-1]
      start,end = location.start,location.end
      if start is None or end is None or not 0 <= start < end <= len(page.text) or page.text[start:end] != supplied.original_text:
        raise ValueError("Restored finding does not match the source PDF")
      if supplied.finding_id in ids:
        raise ValueError("Duplicate restored finding")
      ids.add(supplied.finding_id)
      finding = supplied.model_copy(deep=True)
      finding.location.boxes = pdf.span_boxes(page, start, end)
      position = (start, end, finding.field_type)
      finding.finding_id = hashlib.sha256(f"{document_id}|{location.page_number}|{position}".encode()).hexdigest()[:20]
      normalised = " ".join(finding.original_text.casefold().split())
      finding.entity_id = hashlib.sha256(f"{document_id}|{finding.field_type}|{normalised}".encode()).hexdigest()[:12]
      finding.replacement = session.tokens.assign(finding.field_type, finding.original_text)
      restored.append(finding)
    session.spacy_spans = [[] for _ in session.extracted.pages]
    session.predictions = [[] for _ in session.extracted.pages]
    for finding in restored:
      for level in finding.sensitivity_levels:
        session.spacy_spans[finding.location.page_number-1].append(dict(
          start=finding.location.start, end=finding.location.end, field_type=finding.field_type,
          level=level, subcategory=finding.subcategory, detector=finding.detector, reason=finding.reason))
    session.review.findings = restored
    session.review.analysed = True
    session.review.revision = 1
    session.review.processing = "Recovered browser review; original text and coordinates verified. Re-run detection to update candidates."
    session.review.languages = request.context.languages
    session.context = request.context
    session.review.review_set = request.context.review_set
    session.expires = time.monotonic() + _config.SESSION_SECONDS
    return session.review.model_copy(deep=True)


def quality_review(document_id, request):
  from . import llm_review
  session=store.get(document_id)
  with session.lock:
    if not session.review.analysed or request.revision != session.review.revision:
      raise ValueError('Refresh the current findings before the quality check.')
    previous=session.review.model_copy(deep=True)
    by_id={f.finding_id:f for f in session.review.findings}
    try:
      for decision in request.decisions:
        if decision.finding_id not in by_id:
          raise ValueError('Unknown reviewed finding')
        f=by_id[decision.finding_id]
        f.selected=decision.selected
        f.review_status='confirmed_remove' if decision.selected else 'confirmed_keep'
      result=llm_review.review(session)
      changed=protected=0
      for change in result['changes']:
        f=by_id[change.finding_id]
        if f.review_status != 'unreviewed' or f.review_signal == 'approved':
          protected+=1;continue
        if change.action=='keep' and f.field_type=='person_name':
          protected+=1;continue
        f.field_type=change.field_type
        from .legal_references import info as reference_info
        f.legal_reference=reference_info(f.original_text) if f.field_type=="case_reference" else None
        f.sensitivity_levels=list(dict.fromkeys(change.sensitivity_levels))
        f.selected=change.action!='keep'
        f.context_suggestion=change.action
        f.context_reason=change.reason[:600]
        f.reason='LLM quality check: '+change.reason[:600]
        f.detector=f.detector+' + openai-quality' if 'openai-quality' not in f.detector else f.detector
        f.replacement=session.tokens.assign(f.field_type,f.original_text)
        changed+=1
      additions=0
      existing={(f.location.page_number,f.location.start,f.location.end,f.field_type) for f in session.review.findings}
      for add in result['additions']:
        identity=(add['page'],add['start'],add['end'],add['field_type'])
        if identity in existing: continue
        page=session.extracted.pages[add['page']-1]
        spans=[dict(start=add['start'],end=add['end'],field_type=add['field_type'],level=level,
          subcategory='quality_check',detector='openai-quality',reason=add['reason']) for level in add['levels']]
        found=rules.findings_for_page(document_id,page,[],Context(),spans,session.layout_regions)
        for f in found:
          if 'openai-quality' not in f.detector: continue
          f.replacement=session.tokens.assign(f.field_type,f.original_text)
          session.review.findings.append(f);existing.add(identity);additions+=1
      layout.annotate(session.review.findings,session.extracted.pages,session.layout_regions)
      session.review.revision+=1
      session.review.quality_check={k:v for k,v in result.items() if k not in {'changes','additions'}}
      session.review.quality_check.update(changed=changed,added=additions,protected=protected)
      session.review.processing+=' + OpenAI quality check'
      return session.review.model_copy(deep=True)
    except Exception:
      session.review=previous
      raise
