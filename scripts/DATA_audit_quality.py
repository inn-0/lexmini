# scripts/DATA_audit_quality.py
"""Recalculate the public Swiss example's date coverage from cached model output.

Rationale: keep a repeatable quality check without a GPU call on every review.
Assumptions: the source PDF and the manually reviewed date inventory are unchanged.
Constraints: count occurrences, not unique dates; never treat coverage as PII recall.
"""

import hashlib
import json
from pathlib import Path as pPath

from lexmini.pdf import extract
from lexmini.rules import findings_for_page
from lexmini.schemas import Context


def main():
  root = pPath(__file__).resolve().parents[1]
  folder = root / "data/quality"
  cache = json.loads((folder / "CH_BVGE_001_E-1088-2022_2022-11-07.baseline.json").read_text())
  inventory = json.loads((folder / "date_inventory.json").read_text())
  payload = (root / cache["pdf_path"]).read_bytes()
  assert hashlib.sha256(payload).hexdigest() == cache["pdf_sha256"]
  pages = extract(payload).pages
  current = []
  for page, cached in zip(pages, cache["pages"], strict=True):
    assert hashlib.sha256(page.text.encode()).hexdigest() == cached["text_sha256"]
    current.append(findings_for_page("quality-audit", page, cached["spans"], Context()))
  records = []
  for item in inventory["dates"]:
    page_index = item["page"] - 1
    assert pages[page_index].text[item["start"]:item["end"]] == item["text"]
    spans = cache["pages"][page_index]["spans"]
    def covers(start, end):
      return start <= item["start"] and end >= item["end"]
    raw = [s for s in spans if s["label"] == "private_date"]
    baseline_full = any(covers(s["start"], s["end"]) for s in raw)
    overlap = any(s["start"] < item["end"] and s["end"] > item["start"] for s in raw)
    enhanced_full = any(covers(f.location.start, f.location.end)
      for f in current[page_index] if f.field_type in ("date", "birth_date"))
    records.append({**item, "baseline": "full" if baseline_full else "partial" if overlap else "missed",
      "current_rules_full": enhanced_full})
  result = {"pdf_sha256": cache["pdf_sha256"], "denominator": len(records),
    "measure": "Full span coverage of independently reviewed day-month occurrences, including heading; not general PII recall",
    "baseline_full": sum(r["baseline"] == "full" for r in records),
    "baseline_partial": sum(r["baseline"] == "partial" for r in records),
    "baseline_missed": sum(r["baseline"] == "missed" for r in records),
    "current_rules_full": sum(r["current_rules_full"] for r in records), "dates": records}
  (folder / "date_coverage.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
  print(json.dumps({k: v for k, v in result.items() if k != "dates"}, indent=2))


if __name__ == "__main__":
  main()
