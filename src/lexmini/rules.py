# src/lexmini/rules.py
"""Explainable legal additions to Privacy Filter; these are rules, not a fine-tuned model."""

import hashlib
import re

from .pdf import PageText, span_boxes
from .schemas import Context, Finding, Location
from .dates import date_spans
from .matching import find_matches
from .paragraphs import build as build_paragraphs
from .legal_references import spans as reference_spans, info as reference_info

MODEL_TYPES = {
  "private_person": ("person_name", "personal-private", "identity"),
  "private_address": ("address", "personal-private", "identity"),
  "private_email": ("email", "personal-private", "contact"),
  "private_phone": ("phone", "personal-private", "contact"),
  "private_date": ("date", "personal-private", "identity"),
  "account_number": ("account_number", "personal-private", "financial"),
  "private_url": ("private_url", "personal-private", "contact"),
  "secret": ("credential", "professional-secrecy", "access_secret"),
}

# Small multilingual seed list. The team can extend it without changing the model.
CONCEPTS = [
  {"concept_id": "legal.strategy", "parent_id": "legal", "field_type": "legal_content", "subcategory": "legal_work",
   "labels": {"en": "litigation strategy", "de": "Prozessstrategie", "fr": "stratégie judiciaire", "it": "strategia processuale"}},
  {"concept_id": "business.secret", "parent_id": "business", "field_type": "business_secret", "subcategory": "business_secret",
   "labels": {"en": "trade secret", "de": "Geschäftsgeheimnis", "fr": "secret commercial", "it": "segreto commerciale"}},
  {"concept_id": "personal.health", "parent_id": "personal", "field_type": "medical_information", "subcategory": "health",
   "labels": {"en": "diagnosis", "de": "Diagnose", "fr": "diagnostic", "it": "diagnosi"}},
  {"concept_id": "personal.criminal", "parent_id": "personal", "field_type": "criminal_record", "subcategory": "criminal_history",
   "labels": {"en": "criminal record", "de": "Vorstrafe", "fr": "casier judiciaire", "it": "precedenti penali"}},
]


def rule_spans(text: str, context: Context, paragraphs=None) -> list[dict]:
  result = []

  def add(start, end, field_type, level, subcategory, reason, detector="legal-rule"):
    result.append(dict(start=start, end=end, field_type=field_type, level=level,
      subcategory=subcategory, reason=reason, detector=detector))

  patterns = [
    (r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "email"),
    (r"(?<!\w)(?:\+|00)\d{1,3}[ \t.-]*(?:\(?\d{1,4}\)?[ \t.-]*){2,5}\d{2}(?!\w)", "phone"),
    (r"\b0\d{2}[ \t.-]\d{3}[ \t.-]\d{2}[ \t.-]\d{2}\b", "phone"),
    (r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b", "account_number"),
    (r"\b756\.\d{4}\.\d{4}\.\d{2}\b", "personal_identifier"),
  ]
  for pattern, field_type in patterns:
    for match in re.finditer(pattern, text):
      if field_type == "account_number":
        value = match.group().replace(' ', '')
        # Validate the IBAN check digits to avoid labelling ordinary case references.
        digits = ''.join(str(ord(c)-55) if c.isalpha() else c for c in value[4:] + value[:4])
        if not 15 <= len(value) <= 34 or int(digits) % 97 != 1:
          continue
      add(*match.span(), field_type, "personal-private", "contact_identifier",
        "Structured contact or identifier pattern matched; review its context.", "contact-rule")

  # Company suffixes and role labels supplement the model's fixed personal-data labels.
  company = r"\b[A-ZÀ-Ý][\wÀ-ÿ&'-]*(?:[ \t]+[A-ZÀ-Ý][\wÀ-ÿ&'-]*){0,3}(?:[ \t]+\([^\n)]{1,50}\))?[ \t]+(?:AG|GmbH|SA|Sàrl|SARL|Ltd|LLC|Inc)\b"
  for match in re.finditer(company, text):
    add(*match.span(), "organisation_name", "professional-secrecy", "party", "Company name matched a company suffix.")
  party = r"(?im)\b(?:client|mandant|mandantin|kläger|beklagte|claimant|defendant|cliente)\s*:\s*([^\n;,]{2,100})"
  for match in re.finditer(party, text):
    add(*match.span(1), "organisation_name", "professional-secrecy", "party", "Name follows a client or party label; check the entity type.")
  for match in re.finditer(r"\b(?:CHF|EUR|USD)\s*[\d][\d'’., ]*\d\b", text):
    add(*match.span(), "amount", "professional-secrecy", "matter_detail", "Financial amount may identify the matter.")
  for match in date_spans(text):
    reason = "Date pattern matched. Check whether it describes a person, the matter or a cited law."
    if not match["year_present"]:
      reason += " The year is not written in this mention."
    add(match["start"], match["end"], "date", "professional-secrecy", "matter_detail", reason, "date-rule")
  for term in context.confidential_terms:
    for start, end, kind in find_matches(text, term, "confidential_term", context.fuzzy_matching):
      add(start, end, "confidential_term", "professional-secrecy", "matter_detail",
        "Matches your entered term." if kind == "exact" else "Similar to your entered term; check this spelling before removing it.", "user-term" if kind == "exact" else "user-term-fuzzy")
  result.extend(reference_spans(text))
  # Sensitive-topic rules use sentences inside Docling paragraphs, never PDF lines.
  units = paragraphs or []
  if not units:
    from .paragraphs import Paragraph
    units = [Paragraph(page_number=1, text=text.replace("\n", " "), offsets=list(range(len(text))), source="fallback", label="text")]
  for paragraph in units:
    boundaries = [0, *[m.end() for m in re.finditer(r"(?<=[.!?])\s+(?=[A-ZÀ-Ý])", paragraph.text)], len(paragraph.text)]
    for concept in CONCEPTS:
      terms = list(concept["labels"].values())
      if concept["concept_id"] == "personal.health":
        terms += ["dépressif", "dépressive", "traitement médicamenteux"]
      for term in terms:
        for match in re.finditer(r"\b" + re.escape(term) + r"\b", paragraph.text, re.IGNORECASE):
          start = max(b for b in boundaries if b <= match.start())
          end = next(b for b in boundaries if b >= match.end())
          while end > start and paragraph.text[end-1].isspace():
            end -= 1
          level = "personal-private" if concept["concept_id"].startswith("personal.") else "professional-secrecy"
          for a,b in paragraph.ranges(start, end, text):
            add(a, b, concept["field_type"], level, concept["subcategory"],
              f"Sentence contains the sensitive-topic term: {term}. Uses {paragraph.source} paragraph context; review the whole sentence.", "concept-rule")
  return result


def findings_for_page(document_id: str, page: PageText, spans: list[dict], context: Context, extra_spans: list[dict] | None = None, regions=None) -> list[Finding]:
  candidates = []
  for span in spans:
    if span["label"] not in MODEL_TYPES:
      raise ValueError("Model returned an unsupported field type")
    field_type, level, subcategory = MODEL_TYPES[span["label"]]
    start, end = span["start"], span["end"]
    if not 0 <= start < end <= len(page.text) or page.text[start:end] != span["text"]:
      raise ValueError("Model findings do not match the PDF text positions")
    candidates.append(dict(start=start, end=end, field_type=field_type, level=level,
      subcategory=subcategory, detector="openai/privacy-filter", reason=f"Privacy Filter detected {field_type.replace('_', ' ')}."))
  candidates.extend(rule_spans(page.text, context, build_paragraphs(page, regions or [])))
  candidates.extend(extra_spans or [])
  # General NER can mistake a medication list for places. Limit this override
  # to an explicit medication clause, retaining real locations elsewhere.
  medication_lists = [m.span(1) for m in re.finditer(
    r"traitement\s+médicamenteux\s*\(([^)]*)\)", page.text, re.IGNORECASE)]
  candidates = [s for s in candidates if not (s["field_type"] == "address" and s["detector"].startswith("spacy/")
    and any(a <= s["start"] and s["end"] <= b for a,b in medication_lists))]
  # A partial model date must not leave a second checkbox inside a full date.
  complete_dates = [s for s in candidates if s["detector"] == "date-rule"]
  for span in candidates:
    if span["field_type"] == "date" and (span["detector"] == "openai/privacy-filter" or span["detector"].startswith("spacy/")):
      outer = next((s for s in complete_dates if s["start"] <= span["start"] and s["end"] >= span["end"]), None)
      if outer:
        span["start"], span["end"] = outer["start"], outer["end"]
  # Combine exact duplicate detections without discarding either sensitivity.
  merged = {}
  for span in candidates:
    key = (span["start"], span["end"], span["field_type"])
    if key not in merged:
      merged[key] = {**span, "levels": [span["level"]]}
    else:
      previous = merged[key]
      previous["levels"] = list(dict.fromkeys([*previous["levels"], span["level"]]))
      if span["detector"] not in previous["detector"].split(" + "):
        previous["detector"] += " + " + span["detector"]
      if span["reason"] not in previous["reason"]:
        previous["reason"] += " " + span["reason"]
  output = []
  for span in merged.values():
    if "public" in span["levels"] and len(span["levels"])>1:
      span["levels"].remove("public")
    start, end, field_type = span["start"], span["end"], span["field_type"]
    key = (start, end, field_type)
    original = page.text[start:end]
    normalised = " ".join(original.casefold().split())
    entity = hashlib.sha256(f"{document_id}|{field_type}|{normalised}".encode()).hexdigest()[:12]
    finding_id = hashlib.sha256(f"{document_id}|{page.info.number}|{key}".encode()).hexdigest()[:20]
    suggestion, context_reason = "review", None
    # Context guidance is explicit and limited. No document is sent to a second LLM.
    goal = " ".join([context.goal, *context.retain_requests]).casefold()
    translator = bool(re.search(r"translat|übersetz|traduct|tradutt", context.role, re.I))
    keep_requested = bool(re.search(r"keep|retain|preserv|behalt|conserv|garder", goal))
    kind_requested = ((field_type == "date" and bool(re.search(r"date|datum|daten", goal))) or
      (field_type == "amount" and bool(re.search(r"amount|payment|betrag|beträge|montant|import", goal))))
    if field_type in context.retain_requests or (translator and keep_requested and kind_requested):
      suggestion = "keep"
      context_reason = "Your keep request includes this field type. Check this mention before keeping it; the rule does not determine its purpose."
    default_selected = field_type != "date"
    if field_type == "date":
      nearby = page.text[max(0,start-90):min(len(page.text),end+90)].casefold()
      default_selected = bool(re.search(r"birth|born|birthday|naissance|né[e]? le|geburt|geboren|nascita|nato",nearby))
      context_reason = "Possible birth date; review before release." if default_selected else "Ordinary date kept by default; check if it identifies the confidential matter."
      suggestion = "remove" if default_selected else "keep"
    if field_type == 'case_reference':
      default_selected = span['subcategory'] in {'internal_file'}
    output.append(Finding(selected=default_selected,
      legal_reference=reference_info(original,span['subcategory']) if field_type=='case_reference' else None,finding_id=finding_id, entity_id=entity, field_type=field_type,
      original_text=original, location=Location(page_number=page.info.number, start=start, end=end,
      boxes=span_boxes(page, start, end)), sensitivity_levels=span["levels"],
      subcategory=span["subcategory"], detector=span["detector"], reason=span["reason"],
      context_suggestion=suggestion, context_reason=context_reason,
      excerpt_before=re.sub(r"\s+", " ", page.text[max(0, start - 110):start]),
      excerpt_after=re.sub(r"\s+", " ", page.text[end:end + 110]),
      replacement=None))
  return sorted(output, key=lambda f: (f.location.start, f.location.end))
