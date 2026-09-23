# scripts/RUN_modal_screening.py
"""Run spaCy and Docling layout on one private CPU worker.

Rationale: keep web instances light and avoid paid language-model API calls.
Assumptions: existing Modal credentials and public model-cache volume.
Constraints: no document logging or persistence; OCR is off, and Docling regions
are advisory. Canonical text and redaction coordinates remain with the caller.
"""

import modal

from lexmini import _config

app = modal.App(_config.SCREENING_APP)
volume = modal.Volume.from_name("ml-multimodal-model-cache-v1", create_if_missing=False)
HERON_REVISION = "8f39ad3c0b4c58e9c2d2c84a38465abf757272d8"
image = (
  modal.Image.debian_slim(python_version="3.13")
  .apt_install("libgl1", "libglib2.0-0")
  .pip_install("torch==2.10.0", "torchvision==0.25.0", extra_index_url="https://download.pytorch.org/whl/cpu")
  .pip_install("docling==2.110.0", "docling-core==2.86.0", "docling-ibm-models==3.13.3",
    "docling-parse==7.5.0", "transformers==5.5.4", "spacy==3.8.16", "numpy==2.4.4", "pymupdf==1.28.2",
    *[f"https://github.com/explosion/spacy-models/releases/download/{name}-3.8.0/{name}-3.8.0-py3-none-any.whl"
      for name in ("de_core_news_lg", "fr_core_news_lg", "it_core_news_lg", "en_core_web_lg")])
  .env({"HF_HOME": "/model-cache/huggingface", "HF_HUB_DISABLE_TELEMETRY": "1",
    "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2", "TOKENIZERS_PARALLELISM": "false"})
  .add_local_python_source("lexmini")
)


@app.cls(image=image, cpu=2, memory=8192, volumes={"/model-cache": volume},
  timeout=900, startup_timeout=1200, scaledown_window=60, max_containers=2)
@modal.concurrent(max_inputs=1)
class DocumentScreening:
  @modal.enter()
  def load(self):
    self.converter = None

  def layout(self, payload):
    import io
    from docling.datamodel.base_models import DocumentStream, InputFormat, ConversionStatus
    from docling.datamodel.layout_model_specs import DOCLING_LAYOUT_HERON
    from docling.datamodel.pipeline_options import PdfPipelineOptions, LayoutOptions, AcceleratorOptions, AcceleratorDevice
    from docling.document_converter import DocumentConverter, PdfFormatOption
    if self.converter is None:
      options = PdfPipelineOptions(do_ocr=False, do_table_structure=False)
      options.accelerator_options = AcceleratorOptions(num_threads=2, device=AcceleratorDevice.CPU)
      options.layout_options = LayoutOptions(model_spec=DOCLING_LAYOUT_HERON.model_copy(update={"revision": HERON_REVISION}))
      self.converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})
    result = self.converter.convert(DocumentStream(name="document.pdf", stream=io.BytesIO(payload)), max_num_pages=40)
    if result.status != ConversionStatus.SUCCESS:
      raise ValueError("Docling did not complete every page; no layout result was applied")
    regions = []
    for item, _ in result.document.iterate_items():
      for provenance in getattr(item, "prov", []):
        size = result.document.pages[provenance.page_no].size
        box = provenance.bbox.to_top_left_origin(page_height=size.height)
        regions.append(dict(page_number=provenance.page_no, label=item.label.value,
          box=[box.l, box.t, box.r, box.b], text=getattr(item, "text", "")))
    volume.commit()
    return regions

  @modal.method()
  def screen(self, texts: list[str], languages: list[str], payload: bytes = b"") -> dict:
    import hashlib
    from lexmini.spacy_detector import detect
    if len(texts) > 40 or sum(map(len, texts)) > 200000 or len(payload) > 20 * 1024 * 1024:
      raise ValueError("Document exceeds prototype limits")
    if payload and not payload.startswith(b"%PDF-"):
      raise ValueError("Layout input must be a PDF")
    regions = self.layout(payload) if payload else []
    if payload:
      from lexmini import pdf, paragraphs
      from lexmini.layout import LayoutRegion
      pages = pdf.extract(payload).pages
      if [p.text for p in pages] != texts:
        raise ValueError("Worker PDF character positions differ from the review source")
      spans = paragraphs.detect(pages, [LayoutRegion.model_validate(r) for r in regions], languages, detect)
    else:
      spans = detect(texts, languages)
    return {"spacy_spans": spans, "regions": regions,
      "text_hashes": [hashlib.sha256(t.encode()).hexdigest() for t in texts],
      "pdf_sha256": hashlib.sha256(payload).hexdigest() if payload else None,
      "engine": "spaCy 3.8.16 on Modal CPU" + (" + Docling 2.110.0 / Heron paragraphs v1" if payload else "")}


@app.local_entrypoint()
def smoke():
  result = DocumentScreening().screen.remote(["William Waeber, juge à Berne."], ["fr"])
  print({"engine": result["engine"], "span_count": len(result["spacy_spans"][0])})
