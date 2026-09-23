# scripts/DATA_cache_screening.py
# Rationale: save reproducible public spaCy/Docling checks without repeat inference.
# Assumptions: frozen reference PDFs and the deployed private CPU worker exist.
# Constraints: public fixtures only, verify every source hash, never read uploads.

import hashlib
import json
from pathlib import Path as pPath

import modal

from lexmini import _config, pdf

LANGUAGES = {"CH_BVGE_001_E-1088-2022_2022-11-07": "fr",
  "CH_BVGE_001_C-6081-2022_2023-01-20": "it", "CUAD_07_Hosting": "en"}


def main():
  worker = modal.Cls.from_name(_config.SCREENING_APP, _config.SCREENING_CLASS)()
  root = pPath(__file__).resolve().parents[1]
  for name, language in LANGUAGES.items():
    baseline = json.loads((root / "data/quality" / f"{name}.baseline.json").read_text())
    source = (root / baseline["pdf_path"]).resolve()
    if not source.is_relative_to((root / "data/reference").resolve()):
      raise ValueError("Only public reference fixtures can be cached")
    payload = source.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == baseline["pdf_sha256"]
    texts = [p.text for p in pdf.extract(payload).pages]
    assert [hashlib.sha256(t.encode()).hexdigest() for t in texts] == [p["text_sha256"] for p in baseline["pages"]]
    result = worker.screen.remote(texts, [language], payload)
    result["languages"] = [language]
    result["schema_version"] = 1
    target = root / "data/quality" / f"{name}.screening.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"sample": name, "pages": len(texts), "regions": len(result["regions"]),
      "spans": sum(len(p) for p in result["spacy_spans"])}), flush=True)


if __name__ == "__main__":
  main()
