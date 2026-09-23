# src/lexmini/tokens.py
"""Document-scoped tokens. Original values stay separate from shared output."""

import html
import io

import pymupdf
from pydantic import BaseModel, Field

PREFIXES = {"person_name": "PARTY", "organisation_name": "PARTY", "date": "DATE",
  "birth_date": "BIRTH_DATE", "confidential_term": "TERM", "account_number": "ACCOUNT"}


class TokenRegistry(BaseModel):
  values: dict[str, dict[str, str]] = Field(default_factory=dict)
  lookup: dict[str, str] = Field(default_factory=dict)
  counters: dict[str, int] = Field(default_factory=dict)

  def assign(self, field_type: str, original: str) -> str:
    prefix = PREFIXES.get(field_type, field_type.upper())
    key = prefix + "|" + " ".join(original.casefold().split())
    if key not in self.lookup:
      number = self.counters.get(prefix, 0) + 1
      self.counters[prefix] = number
      token = f"[{prefix}_{number:05d}]"
      self.lookup[key] = token
      self.values[token] = {"original_text": original, "field_type": field_type}
    return self.lookup[key]


def replace_pages(pages, findings, registry: TokenRegistry, style: str) -> list[str]:
  output = []
  for number, page in enumerate(pages, 1):
    spans = sorted((f for f in findings if f.location.page_number == number),
      key=lambda f: (f.location.start, -f.location.end, f.field_type))
    groups = []
    for finding in spans:
      start, end = finding.location.start, finding.location.end
      if groups and start < groups[-1][1]:
        groups[-1][1] = max(groups[-1][1], end)
        groups[-1][2].append(finding)
      else:
        groups.append([start, end, [finding]])
    text = page.text
    for start, end, members in reversed(groups):
      # A wider overlap needs its own key, so restoration cannot lose extra words.
      outer = next((f for f in members if f.location.start == start and f.location.end == end), None)
      field_type = outer.field_type if outer else "text"
      token = registry.assign(field_type, page.text[start:end])
      text = text[:start] + (token if style == "tokens" else "[X]") + text[end:]
    output.append(text)
  return output


def reflow_pdf(pages: list[str]) -> bytes:
  """Build readable tokenised pages from clean text, without original PDF objects."""
  buffer = io.BytesIO()
  writer = pymupdf.DocumentWriter(buffer)
  for text in pages:
    body = "<br>".join(html.escape(text).splitlines())
    story = pymupdf.Story(html=f"<div>{body}</div>",
      user_css="body {font-family: sans-serif; font-size: 11pt;}")
    more = True
    while more:
      device = writer.begin_page(pymupdf.Rect(0, 0, 595, 842))
      more, _ = story.place(pymupdf.Rect(40, 40, 555, 802))
      story.draw(device)
      writer.end_page()
  writer.close()
  return buffer.getvalue()
