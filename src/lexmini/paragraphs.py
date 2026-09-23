# src/lexmini/paragraphs.py
"""Docling paragraph boundaries with an exact map back to PDF characters.

Docling supplies layout, never invented coordinates. Unassigned characters remain
in explicitly labelled fallback runs so extraction gaps cannot silently drop text.
"""
import re
from pydantic import BaseModel, Field


class Paragraph(BaseModel):
  page_number: int
  text: str
  offsets: list[int] = Field(default_factory=list)
  source: str
  label: str

  def ranges(self, start, end, original):
    if not 0 <= start < end <= len(self.offsets):
      raise ValueError('Paragraph finding is outside its character map')
    indices = self.offsets[start:end]
    begin = previous = indices[0]
    output = []
    for index in indices[1:]:
      gap = original[previous+1:index]
      if gap.strip().strip('-\u00ad'):
        output.append((begin, previous+1))
        begin = index
      previous = index
    output.append((begin, previous+1))
    return output


def normalise(text, indices):
  characters, offsets = [], []
  for index in indices:
    char = text[index]
    if offsets and index > offsets[-1]+1 and characters[-1] != ' ':
      characters.append(' ')
      offsets.append(offsets[-1]+1)
    if char == '\u00ad':
      continue
    if char.isspace():
      if characters and characters[-1] != ' ':
        characters.append(' ')
        offsets.append(index)
    else:
      characters.append(char)
      offsets.append(index)
  while characters and characters[-1] == ' ':
    characters.pop(); offsets.pop()
  # Join only explicit word hyphenation across a source line break.
  joined = ''.join(characters)
  remove = set()
  for match in re.finditer(r'(?<=\w)- (?=\w)', joined):
    a,b = match.span()
    if '\n' in text[offsets[a]:offsets[b]]:
      remove.update(range(a,b))
  return ''.join(c for i,c in enumerate(characters) if i not in remove), [v for i,v in enumerate(offsets) if i not in remove]


def build(page, regions):
  local = [r for r in regions if r.page_number == page.info.number and r.label not in {'picture', 'table'}]
  # Narrower regions win where Docling gives nested layout elements.
  local.sort(key=lambda r:(r.box[2]-r.box[0])*(r.box[3]-r.box[1]))
  groups = {}
  fallback = 0
  previous_owner = None
  for index, char in enumerate(page.text):
    box = page.boxes[index]
    if box is None:
      continue
    x,y = (box[0]+box[2])/2, (box[1]+box[3])/2
    owner = next((i for i,r in enumerate(local) if r.box[0]-1 <= x <= r.box[2]+1 and r.box[1]-1 <= y <= r.box[3]+1), None)
    if owner is None:
      if previous_owner is not None:
        fallback += 1
      key = ('fallback', fallback)
    else:
      key = ('docling', owner)
    groups.setdefault(key, []).append(index)
    previous_owner = owner
  result = []
  for (source, identifier), indices in groups.items():
    text, offsets = normalise(page.text, indices)
    if text.strip():
      result.append(Paragraph(page_number=page.info.number, text=text, offsets=offsets,
        source=source, label=local[identifier].label if source == 'docling' else 'unassigned_text'))
  return sorted(result, key=lambda p:p.offsets[0])


def detect(pages, regions, languages, detector):
  paragraphs = [paragraph for page in pages for paragraph in build(page, regions)]
  output = [[] for _ in pages]
  detected = detector([p.text for p in paragraphs], languages)
  if len(detected) != len(paragraphs):
    raise ValueError('Paragraph detector did not return every paragraph')
  for paragraph, spans in zip(paragraphs, detected):
    original = pages[paragraph.page_number-1].text
    for span in spans:
      for start,end in paragraph.ranges(span['start'], span['end'], original):
        output[paragraph.page_number-1].append({**span, 'start':start, 'end':end,
          'reason':span['reason'] + f' Analysed as {paragraph.source} paragraph; mapped to original PDF characters.'})
  return output
