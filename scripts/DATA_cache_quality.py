# scripts/DATA_cache_quality.py
"""Save raw model predictions for an explicitly chosen public example PDF.

Rationale: make review fixtures load without paying for inference again.
Assumptions: inputs come from the downloaded public reference collection.
Constraints: never overwrite a baseline; refuse files outside data/reference.
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path as pPath

import modal

from lexmini import _config, pdf


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("pdf", type=pPath)
  args = parser.parse_args()
  root = pPath(__file__).resolve().parents[1]
  source = args.pdf.resolve()
  source.relative_to(root / "data/reference")
  target = root / "data/quality" / (source.stem + ".baseline.json")
  if target.exists():
    parser.error("Baseline already exists. Preserve it; choose a new explicit fixture version.")
  payload = source.read_bytes()
  extracted = pdf.extract(payload)
  # Legacy GPU benchmark only; the normal application uses the CPU screening worker.
  worker = modal.Cls.from_name(_config.MODAL_APP, _config.MODAL_CLASS)()
  predictions = worker.detect.remote([page.text for page in extracted.pages])
  result = {"schema_version": 1, "pdf_sha256": hashlib.sha256(payload).hexdigest(),
    "pdf_path": str(source.relative_to(root)), "captured_at": datetime.now(timezone.utc).isoformat(),
    "model": {"name": "openai/privacy-filter", "opf_revision": _config.OPF_REVISION,
      "weights_revision": "7ffa9a043d54d1be65afb281eddf0ffbe629385b",
      "service": "Modal private PrivacyFilter.detect", "mode": "one call per extracted page"},
    "pages": [{"text_sha256": hashlib.sha256(page.text.encode()).hexdigest(), "spans": spans}
      for page, spans in zip(extracted.pages, predictions, strict=True)]}
  target.parent.mkdir(parents=True, exist_ok=True)
  with target.open("x") as handle:
    handle.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
  print(f"Saved {target.relative_to(root)}; {len(predictions)} pages.")


if __name__ == "__main__":
  main()
