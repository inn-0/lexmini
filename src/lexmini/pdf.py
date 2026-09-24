# src/lexmini/pdf.py
"""Extract exact character positions and rebuild reviewed output without hidden PDF content."""

from collections import defaultdict

import pymupdf
from pydantic import BaseModel, Field

from . import _config
from .schemas import Finding, PageInfo


class PageText(BaseModel):
  text: str
  boxes: list[tuple[float, float, float, float] | None]
  lines: list[int]
  info: PageInfo


class ExtractedPDF(BaseModel):
  pages: list[PageText]
  metadata: dict[str, str] = Field(default_factory=dict)
  warnings: list[str] = Field(default_factory=list)


def extract(payload: bytes) -> ExtractedPDF:
  if not payload.startswith(b"%PDF-"):
    raise ValueError("Choose a PDF file")
  with pymupdf.open(stream=payload, filetype="pdf") as doc:
    if doc.needs_pass:
      raise ValueError("Unlock the PDF before opening it here")
    if not 1 <= len(doc) <= _config.MAX_PAGES:
      raise ValueError(f"Choose a PDF with 1 to {_config.MAX_PAGES} pages")
    result = ExtractedPDF(pages=[], metadata={k: v for k, v in doc.metadata.items() if v})
    for number, page in enumerate(doc, 1):
      page.set_rotation(0)
      if page.rect.width > 1500 or page.rect.height > 1500:
        raise ValueError("This prototype supports pages up to 1500 PDF points per side")
      chars, boxes, line_ids = [], [], []
      line_id = 0
      for block in page.get_text("rawdict", sort=True)["blocks"]:
        for line in block.get("lines", []):
          for span in line["spans"]:
            for char in span["chars"]:
              for value in char["c"]:
                chars.append(value)
                boxes.append(tuple(char["bbox"]))
                line_ids.append(line_id)
          chars.append("\n")
          boxes.append(None)
          line_ids.append(line_id)
          line_id += 1
      text = "".join(chars)
      readable = bool(text.strip())
      if not readable:
        result.warnings.append(f"Page {number} has no readable text. Scanned pages need OCR; export is disabled.")
      if page.get_images():
        result.warnings.append(f"Page {number} contains images. Text inside images is not checked; inspect them before sharing.")
      result.pages.append(PageText(text=text, boxes=boxes, lines=line_ids,
        info=PageInfo(number=number, width=page.rect.width, height=page.rect.height, readable=readable)))
    if sum(len(p.text) for p in result.pages) > 200000:
      raise ValueError("This document exceeds the prototype limit of 200,000 characters")
    if doc.embfile_count() or any(page.first_annot or page.first_widget for page in doc):
      result.warnings.append("The file has attachments, annotations or form fields. These are excluded from the rebuilt PDF.")
    return result


def span_boxes(page: PageText, start: int, end: int) -> list[tuple[float, float, float, float]]:
  grouped = defaultdict(list)
  for index in range(start, end):
    if page.boxes[index] and not page.text[index].isspace():
      grouped[page.lines[index]].append(pymupdf.Rect(page.boxes[index]))
  rectangles = []
  for boxes in grouped.values():
    merged = boxes[0]
    for box in boxes[1:]:
      merged |= box
    rectangles.append(tuple(merged))
  return rectangles


def page_png(payload: bytes, number: int) -> bytes:
  with pymupdf.open(stream=payload, filetype="pdf") as doc:
    if not 1 <= number <= len(doc):
      raise ValueError("Page does not exist")
    page = doc[number - 1]
    page.set_rotation(0)
    return page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False, annots=False).tobytes("png")


# Colour-blind-friendly category palette; the export includes a labelled legend.
REDACTION_COLOURS = {
  "Party": "0072B2", "Date": "E69F00", "Address": "009E73",
  "Contact": "56B4E9", "Financial": "CC79A7", "Sensitive content": "D55E00",
  "Reference": "F0E442", "Other": "777777",
}
REDACTION_CATEGORIES = {
  "person_name": "Party", "organisation_name": "Party",
  "birth_date": "Date", "date": "Date", "address": "Address",
  "email": "Contact", "phone": "Contact", "private_url": "Contact",
  "account_number": "Financial", "amount": "Financial",
  "case_reference": "Reference", "personal_identifier": "Reference",
  **{key: "Sensitive content" for key in ("medical_information", "belief", "criminal_record",
    "legal_content", "business_secret", "firm_record", "credential", "confidential_term")},
}


def redaction_colour(category):
  value = REDACTION_COLOURS[category]
  return tuple(int(value[i:i+2], 16) / 255 for i in (0, 2, 4))


def _write_safe_text(page, text, rect, visible=False):
  """Position only post-redaction text or generated labels on the clean page."""
  if not text.strip() or rect.is_empty:
    return
  font = pymupdf.Font("helv")
  size = max(1, min(9 if visible else 11, rect.height / (font.ascender - font.descender)))
  width = font.text_length(text, fontsize=size)
  if not width:
    return
  origin = pymupdf.Point(rect.x0, rect.y0 + font.ascender * size)
  writer = pymupdf.TextWriter(page.rect)
  writer.append(origin, text, font=font, fontsize=size)
  scale = min(1, rect.width / width) if visible else rect.width / width
  writer.write_text(page, render_mode=0 if visible else 3,
    morph=(origin, pymupdf.Matrix(scale, 1)), color=(0,0,0))


def export_pdf(payload: bytes, findings: list[Finding], pages=None, registry=None, style="blank") -> bytes:
  """Rebuild the visual page plus permitted selectable text, never original PDF objects."""
  from .tokens import TokenRegistry, replacement_groups
  pages = pages or extract(payload).pages
  registry = registry or TokenRegistry()
  by_page = defaultdict(list)
  for finding in findings:
    category = REDACTION_CATEGORIES.get(finding.field_type, "Other")
    by_page[finding.location.page_number].extend((box, category) for box in finding.location.boxes)
  with pymupdf.open(stream=payload, filetype="pdf") as source, pymupdf.open() as output:
    for number, page in enumerate(source, 1):
      page.set_rotation(0)
      for rect, category in sorted(by_page[number]):
        page.add_redact_annot(pymupdf.Rect(rect), fill=redaction_colour(category))
      if by_page[number]:
        page.apply_redactions(images=2, graphics=2, text=0)
      # Read from the redacted page, never put the original text under an overlay.
      safe_lines = [line for block in page.get_text("dict", sort=True)["blocks"]
        for line in block.get("lines", [])]
      pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False, annots=False)
      categories = [key for key in REDACTION_COLOURS if any(c == key for _, c in by_page[number])]
      columns = max(1, int(page.rect.width // 135))
      footer = 18 + 16 * ((len(categories) + columns - 1) // columns) if categories else 0
      clean = output.new_page(width=page.rect.width, height=page.rect.height + footer)
      clean.insert_image(page.rect, stream=pixmap.tobytes("png"))
      text_runs = [(pymupdf.Rect(span["bbox"]), span["text"], False)
        for line in safe_lines for span in line["spans"]]
      for start, end, label in replacement_groups(pages[number-1],
          [f for f in findings if f.location.page_number == number], registry, style):
        boxes = span_boxes(pages[number-1], start, end)
        if label and boxes:
          text_runs.append((pymupdf.Rect(boxes[0]), label, True))
      for rect, text, visible in sorted(text_runs, key=lambda item:(round(item[0].y0,1),item[0].x0)):
        _write_safe_text(clean, text, rect, visible)
      for index, category in enumerate(categories):
        x = 12 + (index % columns) * 135
        y = page.rect.height + 12 + (index // columns) * 16
        clean.draw_rect(pymupdf.Rect(x, y, x+9, y+9), color=None, fill=redaction_colour(category))
        clean.insert_text((x+14, y+8), category, fontsize=8)
    output.set_metadata({})
    return output.tobytes(garbage=4, deflate=True)


def export_text(pages: list[PageText], findings: list[Finding]) -> str:
  output = []
  for number, page in enumerate(pages, 1):
    spans = sorted((f for f in findings if f.location.page_number == number),
      key=lambda f: (f.location.start, -f.location.end))
    merged = []
    for finding in spans:
      start, end = finding.location.start, finding.location.end
      if merged and start < merged[-1][1]:
        previous = merged[-1]
        same = previous[3] == finding.entity_id
        merged[-1] = (previous[0], max(previous[1], end), previous[2] if same else "[REDACTED]", previous[3])
      else:
        merged.append((start, end, finding.replacement or "[REDACTED]", finding.entity_id))
    text = page.text
    for start, end, replacement, _ in reversed(merged):
      text = text[:start] + replacement + text[end:]
    output.append(text)
  return "\n\n".join(output)
