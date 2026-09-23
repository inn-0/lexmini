# scripts/DATA_export_plain_text.py
"""Put directly readable legal texts in data/text.

Rationale: users should not need to unpack corpus JSON to read examples.
Assumptions: the reference corpus downloads already exist.
Constraints: preserve TAB text exactly so annotation offsets remain valid;
extract complete original PDFs, not the shortened review copies.
"""

import hashlib
import json
from pathlib import Path as pPath

import pymupdf

ROOT = pPath(__file__).resolve().parents[1] / "data"
REFERENCE = ROOT / "reference"
OUTPUT = ROOT / "text"


def main():
  records = []

  def save(relative, text, source, **details):
    path = OUTPUT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = text.encode("utf-8")
    path.write_bytes(payload)
    assert path.read_bytes().decode("utf-8") == text
    records.append({"file": str(path.relative_to(ROOT)), "source_file": source,
      "characters": len(text), "sha256": hashlib.sha256(payload).hexdigest(), **details})

  for split in ("train", "dev", "test"):
    source = REFERENCE / "tab" / f"echr_{split}.json"
    for case in json.loads(source.read_text()):
      save(f"tab/{split}/{case['doc_id']}.txt", case["text"],
        str(source.relative_to(ROOT)), doc_id=case["doc_id"], split=split,
        transformation="none; exact released text; annotation offsets unchanged")

  originals = [("swiss", REFERENCE / "swiss" / item["file"])
    for item in json.loads((REFERENCE / "swiss/manifest.json").read_text())]
  originals += [("cuad", REFERENCE / item["file"])
    for item in json.loads((REFERENCE / "corpora_manifest.json").read_text())
    if item["kind"] == "original contract PDF"]
  for group, source in originals:
    with pymupdf.open(source) as doc:
      pages = [page.get_text(sort=True) for page in doc]
      save(f"{group}/{source.stem}.txt", "\n\f\n".join(pages),
        str(source.relative_to(ROOT)), pages=len(pages),
        transformation="embedded PDF text; sorted reading order; form-feed page separators",
        empty_text_pages=[i for i, text in enumerate(pages, 1) if not text.strip()])
  (OUTPUT / "manifest.json").write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n")
  print(f"Exported and verified {len(records)} UTF-8 text files in {OUTPUT}")


if __name__ == "__main__":
  main()
