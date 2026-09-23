# src/lexmini/layout.py
"""Attach layout evidence without replacing canonical PDF character positions."""

import re
import unicodedata

from pydantic import BaseModel, Field


class LayoutRegion(BaseModel):
  page_number: int = Field(ge=1, le=40)
  label: str = Field(max_length=80)
  box: tuple[float, float, float, float]
  text: str = Field(default="", max_length=200000)


def region_for(finding, regions):
  boxes = finding.location.boxes
  if not boxes:
    return None
  matches = []
  for region in regions:
    if region.page_number != finding.location.page_number:
      continue
    x0, y0, x1, y1 = region.box
    if all(x0 - 2 <= (a+c)/2 <= x1 + 2 and y0 - 2 <= (b+d)/2 <= y1 + 2 for a,b,c,d in boxes):
      matches.append(region)
  return min(matches, key=lambda r: (r.box[2]-r.box[0]) * (r.box[3]-r.box[1]), default=None)


def annotate(findings, pages, regions):
  for finding in findings:
    region = region_for(finding, regions)
    finding.layout_label = region.label if region else None
    detector = finding.detector
    if any(source in detector.split(" + ") for source in ("reviewer-example", "screening-memory", "user-term")):
      finding.review_signal = "approved"
      finding.signal_reason = "Exact match to a reviewer-specified term. Only Save approved term persists it for later documents."
      continue
    if finding.field_type in {"credential", "medical_information", "account_number", "criminal_record", "business_secret"}:
      finding.review_signal = "priority"
      finding.signal_reason = "Review first because of the field type; this is not a confidence score."
      continue
    normalised = ''.join(c for c in unicodedata.normalize('NFKD', finding.original_text.casefold()) if not unicodedata.combining(c)).strip()
    marker = bool(re.fullmatch(r"(?:[A-Z]|[IVXLCDM]{1,6}|\d{1,3})[.)]?", finding.original_text.strip()))
    structural = region and region.label in {"section_header", "page_header", "page_footer", "list_item"}
    if marker and structural and region.text.strip() == finding.original_text.strip():
      finding.review_signal = "weak"
      finding.signal_reason = "Docling identifies this whole region as a section/list marker. Kept by default; review if it identifies a party."
      finding.selected = False
      finding.context_suggestion = "keep"
    elif '-fuzzy' in detector or normalised in {"etat", "m.", "mme", "monsieur", "madame"} or structural:
      finding.review_signal = "weak"
      finding.signal_reason = "Check this approximate match, generic word or heading. Layout is evidence, not an exemption from confidentiality."
    else:
      finding.review_signal = "candidate"
      finding.signal_reason = "Unconfirmed candidate. The detector supplies no calibrated confidence score."
