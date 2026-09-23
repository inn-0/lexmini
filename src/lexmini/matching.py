# src/lexmini/matching.py
"""Repeat matching with original offsets; approximate matches are review candidates.

Normalise case, whitespace and typographic punctuation. Fuzzy matching permits
one edit in long names/phrases, never in dates, numbers, addresses or passwords.
"""

import re
import unicodedata

PUNCTUATION = str.maketrans({"’": "'", "‘": "'", "‐": "-", "‑": "-", "–": "-"})
FUZZY_TYPES = {"person_name", "organisation_name", "confidential_term"}


def normalise(text: str):
  chars, offsets = [], []
  for index, char in enumerate(text):
    value = unicodedata.normalize("NFKC", char).casefold().translate(PUNCTUATION)
    for part in value:
      part = " " if part.isspace() else part
      if part == " " and chars and chars[-1] == " ":
        offsets[-1] = (offsets[-1][0], index + 1)
      else:
        chars.append(part)
        offsets.append((index, index + 1))
  return "".join(chars), offsets


def key(text: str) -> str:
  return normalise(text)[0].strip()


def one_edit(a: str, b: str) -> bool:
  """One insertion, deletion, substitution or adjacent transposition."""
  if a == b or abs(len(a) - len(b)) > 1:
    return False
  if len(a) == len(b):
    differences = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
    if len(differences) == 1:
      return True
    return len(differences) == 2 and differences[1] == differences[0] + 1 and a[differences[0]] == b[differences[1]] and a[differences[1]] == b[differences[0]]
  shorter, longer = (a, b) if len(a) < len(b) else (b, a)
  i = 0
  while i < len(shorter) and shorter[i] == longer[i]:
    i += 1
  return shorter[i:] == longer[i + 1:]


def prepare(text: str):
  normal, offsets = normalise(text)
  return normal, offsets, list(re.finditer(r"\w+(?:['-]\w+)*", normal))


def find_matches(text: str, term: str, field_type: str, fuzzy: bool = True, prepared=None):
  normal, offsets, words = prepared or prepare(text)
  needle = key(term)
  if not needle:
    return []
  result = []
  position = 0
  while True:
    start = normal.find(needle, position)
    if start < 0:
      break
    end = start + len(needle)
    position = start + 1
    if start and needle[0].isalnum() and (normal[start - 1].isalnum() or normal[start - 1] == '_'):
      continue
    if end < len(normal) and needle[-1].isalnum() and (normal[end].isalnum() or normal[end] == '_'):
      continue
    result.append((offsets[start][0], offsets[end - 1][1], "exact"))
  if not fuzzy or field_type not in FUZZY_TYPES or not 8 <= len(needle) <= 120 or not all(c.isalpha() or c in " '-" for c in needle):
    return result
  width = len(re.findall(r"\w+(?:['-]\w+)*", needle))
  if not 1 <= width <= 6:
    return result
  for index in range(len(words) - width + 1):
    start, end = words[index].start(), words[index + width - 1].end()
    candidate = normal[start:end]
    if abs(len(candidate) - len(needle)) > 1 or not all(c.isalpha() or c in " '-" for c in candidate):
      continue
    if one_edit(needle, candidate):
      source_start, source_end = offsets[start][0], offsets[end - 1][1]
      if not any(source_start < old_end and source_end > old_start for old_start, old_end, _ in result):
        result.append((source_start, source_end, "fuzzy"))
  return sorted(result)
