# scripts/DATA_prepare_review_samples.py
"""Prepare real legal PDFs and clearly labelled renderings of released case text.

Rationale: make downloaded legal sources usable in the PDF review interface.
Assumptions: DATA_fetch_legal_corpora.py has downloaded TAB and CUAD.
Constraints: preserve original files; identify excerpts and new PDF layouts.
Swiss sources are already anonymised in part and have no PII gold labels.
"""

import hashlib
import html
import io
import json
from pathlib import Path as pPath

import httpx
import pymupdf

ROOT = pPath(__file__).resolve().parents[1] / "data/reference"
catalogue = []


def record(path, source, language, kind, licence, title):
  with pymupdf.open(path) as doc:
    pages = len(doc)
  catalogue.append({"id": path.stem, "file": str(path.relative_to(ROOT)), "title": title,
    "source": source, "language": language, "kind": kind, "licence": licence,
    "pages": pages, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})


swiss = [
  ("CH_BVGE_001_A-1496-2019_2021-07-16", "de", "Swisscom / Sunrise - access dispute"),
  ("CH_BVGE_001_E-1088-2022_2022-11-07", "fr", "Swiss administrative judgment - French"),
  ("CH_BVGE_001_C-6081-2022_2023-01-20", "it", "Swiss administrative judgment - Italian"),
]
swiss_root = ROOT / "swiss"
swiss_root.mkdir(parents=True, exist_ok=True)
swiss_manifest = []
with httpx.Client(timeout=60, follow_redirects=True) as client:
  for name, language, title in swiss:
    url = f"https://entscheidsuche.ch/docs/CH_BVGer/{name}.pdf"
    path = swiss_root / f"{name}.pdf"
    if not path.exists():
      response = client.get(url)
      response.raise_for_status()
      path.write_bytes(response.content)
    with pymupdf.open(path) as doc:
      original_pages = len(doc)
      swiss_manifest.append({"file": path.name, "url": url, "pages": original_pages,
        "source": "Swiss Federal Administrative Court, via entscheidsuche.ch",
        "reuse_terms": "https://entscheidsuche.ch/dataUsage",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
      if len(doc) > 40:
        with pymupdf.open() as sample:
          sample.insert_pdf(doc, from_page=0, to_page=11)
          path = swiss_root / f"{name}_EXCERPT_pages_1-12.pdf"
          sample.set_metadata({"title": title + " - excerpt, original pages 1-12", "subject": url})
          sample.save(path)
        title += " (pages 1-12)"
    record(path, url, language, "original published PDF" if original_pages <= 40 else "excerpt of original PDF",
      "Free use and adaptation; credit entscheidsuche.ch (publisher terms)", title)
    print(f"Swiss: {name}, {original_pages} original pages", flush=True)
(swiss_root / "manifest.json").write_text(json.dumps(swiss_manifest, indent=2) + "\n")

corpus_manifest = json.loads((ROOT / "corpora_manifest.json").read_text())
for entry in corpus_manifest:
  if entry["kind"] != "original contract PDF":
    continue
  path = ROOT / entry["file"]
  title = path.stem.replace("_", " ")
  if entry["pages"] > 40:
    original = path
    path = path.with_name(path.stem + "_EXCERPT_pages_1-12.pdf")
    with pymupdf.open(original) as doc, pymupdf.open() as sample:
      sample.insert_pdf(doc, from_page=0, to_page=11)
      sample.save(path)
    title += " (pages 1-12)"
  record(path, entry["download_url"], "en", "original contract PDF" if entry["pages"] <= 40 else "excerpt of original PDF", "CC-BY-4.0", title)

tab = json.loads((ROOT / "tab/echr_dev.json").read_text())
# Keep original dev/test membership; favour some Swiss cases when present.
ordered = sorted(tab, key=lambda d: ("CHE" not in str(d["meta"]["countries"]), d["doc_id"]))
tab_pdf_root = ROOT / "tab/review_pdfs"
tab_pdf_root.mkdir(exist_ok=True)
for case in ordered[:10]:
  path = tab_pdf_root / f"TAB_DEV_{case['doc_id']}_TEXT_RENDERING.pdf"
  source = f"https://hudoc.echr.coe.int/eng?i={case['doc_id']}"
  # These are the released introductions/facts, not original full-judgment PDFs.
  with pymupdf.open() as doc:
    story = pymupdf.Story(html=f'<h1>TAB case {html.escape(case["doc_id"])}</h1><p>Real ECHR case text, dev split. New PDF layout; original court layout not reproduced.</p><div style="white-space:pre-wrap">{html.escape(case["text"])}</div>',
      user_css="body {font-family: sans-serif; font-size: 11pt;} h1 {font-size: 17pt;}")
    buffer = io.BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    more = True
    while more:
      device = writer.begin_page(pymupdf.Rect(0, 0, 595, 842))
      more, _ = story.place(pymupdf.Rect(45, 45, 550, 797))
      story.draw(device)
      writer.end_page()
    writer.close()
    path.write_bytes(buffer.getvalue())
  record(path, source, "en", "new PDF rendering of real case text (introduction and facts)", "MIT (TAB corpus)", f"ECHR {case['doc_id']} - real case text")
(ROOT / "sample_catalogue.json").write_text(json.dumps(catalogue, indent=2, ensure_ascii=False) + "\n")
print(f"Prepared {len(catalogue)} real-document review samples")
