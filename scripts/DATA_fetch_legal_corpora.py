# scripts/DATA_fetch_legal_corpora.py
"""Download publisher-released legal corpora with source and licence records.

Rationale: real case text and original contract PDFs complement synthetic tests.
Assumptions: public publisher endpoints are reachable; no credentials are needed.
Constraints: preserve source documents, licences and original train/test splits.
Never describe CUAD clause labels as exhaustive PII annotations.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path as pPath
from urllib.parse import quote

import httpx
import pymupdf

ROOT = pPath(__file__).resolve().parents[1] / "data/reference"
ROOT.mkdir(parents=True, exist_ok=True)
client = httpx.Client(timeout=90, follow_redirects=True)
manifest = []


def fetch(url, target, source, licence, kind):
  target.parent.mkdir(parents=True, exist_ok=True)
  if not target.exists():
    response = client.get(url)
    response.raise_for_status()
    temporary = target.with_suffix(target.suffix + ".partial")
    temporary.write_bytes(response.content)
    temporary.replace(target)
  content = target.read_bytes()
  entry = {"file": str(target.relative_to(ROOT)), "download_url": url, "source": source,
    "licence": licence, "kind": kind, "bytes": len(content),
    "sha256": hashlib.sha256(content).hexdigest(), "checked_at": datetime.now(timezone.utc).isoformat()}
  if target.suffix == ".pdf":
    with pymupdf.open(target) as doc:
      entry.update(pages=len(doc), text_characters=sum(len(p.get_text()) for p in doc))
  manifest.append(entry)
  print(f"Saved {entry['file']} ({entry['bytes']} bytes)", flush=True)
  return target


tab_repo = "NorskRegnesentral/text-anonymization-benchmark"
revision = client.get(f"https://api.github.com/repos/{tab_repo}/commits/master").json()["sha"]
tab_source = f"https://github.com/{tab_repo}/tree/{revision}"
for filename in ["LICENSE.txt", "README.md", "guidelines.md", "echr_train.json", "echr_dev.json", "echr_test.json"]:
  fetch(f"https://raw.githubusercontent.com/{tab_repo}/{revision}/{filename}", ROOT / "tab" / filename,
    tab_source, "MIT", "original annotated case text" if filename.endswith("json") else "source documentation")

cuad_id = "theatticusproject/cuad"
cuad_meta = client.get(f"https://huggingface.co/api/datasets/{cuad_id}").json()
cuad_revision = cuad_meta["sha"]
tree = client.get(f"https://huggingface.co/api/datasets/{cuad_id}/tree/{cuad_revision}/CUAD_v1?recursive=true&limit=1000").json()
source = "https://www.atticusprojectai.org/cuad/"
readme = next(x["path"] for x in tree if x["path"].endswith("CUAD_v1_README.txt"))
fetch(f"https://huggingface.co/datasets/{cuad_id}/resolve/{cuad_revision}/{quote(readme)}",
  ROOT / "cuad/README_source.txt", source, "CC-BY-4.0", "source documentation")
fetch(source, ROOT / "cuad/publisher_page.html", source, "CC-BY-4.0", "licence evidence")
pdfs = [x for x in tree if x["path"].endswith(".pdf") and "full_contract_pdf" in x["path"]]
# Choose varied contract types, avoiding a sample dominated by one company.
seen, chosen = set(), []
for item in sorted(pdfs, key=lambda x: x["path"]):
  category = pPath(item["path"]).parent.name
  if category in seen or item.get("size", 0) > 1500000:
    continue
  seen.add(category)
  chosen.append(item)
  if len(chosen) == 12:
    break
for index, item in enumerate(chosen, 1):
  category = pPath(item["path"]).parent.name.replace(" ", "_")
  fetch(f"https://huggingface.co/datasets/{cuad_id}/resolve/{cuad_revision}/{quote(item['path'])}",
    ROOT / "cuad/pdfs" / f"CUAD_{index:02d}_{category}.pdf", source, "CC-BY-4.0", "original contract PDF")

(ROOT / "corpora_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
client.close()
print(f"Recorded {len(manifest)} source files")
