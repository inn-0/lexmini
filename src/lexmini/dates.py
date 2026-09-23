# src/lexmini/dates.py
"""Date candidates for review, preserving exact source offsets without OCR.

Month names cover French, German, Italian and English. A recognised date is
not proof of private information. Do not silently normalise the PDF text.
"""

import re
from datetime import date

MONTHS = [
  (1, "janvier januar gennaio january jan"),
  (2, "février fevrier februar febbraio february feb"),
  (3, "mars märz maerz marzo march mar"),
  (4, "avril april aprile apr"),
  (5, "mai maggio may"),
  (6, "juin juni giugno june jun"),
  (7, "juillet juli luglio july jul"),
  (8, "août aout august agosto aug"),
  (9, "septembre september settembre sept sep"),
  (10, "octobre oktober ottobre october oct okt"),
  (11, "novembre november nov"),
  (12, "décembre decembre dezember dicembre december dec dez"),
]
MONTH_NUMBER = {name: number for number, names in MONTHS for name in names.split()}
MONTH_PATTERN = "(?:" + "|".join(sorted(MONTH_NUMBER, key=len, reverse=True)) + ")"
DAY = r"(?P<day>\d{1,2})(?!\d)(?:er|st|nd|rd|th|º|°|\.)?"
YEAR = r"(?P<year>(?:18|19|20|21)\d{2})"
WRITTEN = re.compile(r"\b" + DAY + r"\s+(?P<month>" + MONTH_PATTERN + r")\b\.?" + r"(?:\s+" + YEAR + r"\b)?", re.I)
ENGLISH = re.compile(r"\b(?P<month>" + MONTH_PATTERN + r")\b\.?\s+" + DAY + r"(?:,?\s+" + YEAR + r"\b)?", re.I)
NUMERIC = re.compile(r"\b(?:(?P<iso_year>\d{4})-(?P<iso_month>\d{2})-(?P<iso_day>\d{2})|(?P<day>\d{1,2})(?P<sep>[./])(?P<month>\d{1,2})(?P=sep)(?P<year>\d{4}))\b")
# Court headings sometimes space every letter and digit. Match them in place.
SPACED_MONTH = "(?:" + "|".join(r"[ \t]+".join(name) for name in MONTH_NUMBER if len(name) >= 4) + ")"
SPACED = re.compile(r"\b(?P<day>\d(?:[ \t]*\d)?)[ \t]+(?P<month>" + SPACED_MONTH + r")[ \t]+(?P<year>[12][ \t]+[089][ \t]+\d[ \t]+\d)\b", re.I)


def date_spans(text: str) -> list[dict]:
  candidates = []
  for pattern, kind in [(NUMERIC, "numeric"), (WRITTEN, "written"), (ENGLISH, "written"), (SPACED, "spaced")]:
    for match in pattern.finditer(text):
      data = match.groupdict()
      year = data.get("iso_year") or data.get("year")
      month = data.get("iso_month") or data.get("month")
      day = data.get("iso_day") or data["day"]
      compact_month = re.sub(r"\s", "", month).casefold()
      number = int(compact_month) if compact_month.isdigit() else MONTH_NUMBER[compact_month]
      try:
        # Leap year permits 29 February when the year is absent.
        date(int(re.sub(r"\s", "", year)) if year else 2000, number, int(re.sub(r"\s", "", day)))
      except ValueError:
        continue
      candidates.append({"start": match.start(), "end": match.end(), "kind": kind, "year_present": bool(year)})
  # Longer matches win; English month-first matches can overlap day-first ones.
  accepted = []
  for candidate in sorted(candidates, key=lambda s: (-(s["end"] - s["start"]), s["start"])):
    if not any(candidate["start"] < old["end"] and candidate["end"] > old["start"] for old in accepted):
      accepted.append(candidate)
  return sorted(accepted, key=lambda s: s["start"])
