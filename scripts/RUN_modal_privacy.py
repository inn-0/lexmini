# scripts/RUN_modal_privacy.py
"""Serve OpenAI Privacy Filter through authenticated Modal function calls.

Rationale: keep model weights outside the browser and reuse Modal credentials.
Assumptions: the existing Modal profile can deploy to its own workspace.
Constraints: no public inference endpoint; no document logging or persistence.
Only public model weights are saved to the shared model volume.
"""

import modal

from lexmini import _config

app = modal.App(_config.MODAL_APP)
volume = modal.Volume.from_name("ml-multimodal-model-cache-v1", create_if_missing=False)
image = (
  modal.Image.debian_slim(python_version="3.12")
  .apt_install("git")
  .pip_install("torch==2.10.0", "huggingface-hub==1.10.2", "numpy==2.4.4",
    "safetensors==0.7.0", "tiktoken==0.12.0",
    f"opf @ git+https://github.com/openai/privacy-filter.git@{_config.OPF_REVISION}")
  .env({"HF_HOME": "/model-cache/huggingface", "HF_HUB_DISABLE_TELEMETRY": "1"})
  .add_local_python_source("lexmini")
)


@app.cls(image=image, gpu="L4", volumes={"/model-cache": volume},
  timeout=600, startup_timeout=1200, scaledown_window=60, max_containers=1)
@modal.concurrent(max_inputs=1)
class PrivacyFilter:
  @modal.enter()
  def load(self):
    from pathlib import Path as pPath
    from huggingface_hub import snapshot_download
    from opf import OPF

    checkpoint = snapshot_download("openai/privacy-filter",
      revision="7ffa9a043d54d1be65afb281eddf0ffbe629385b", allow_patterns=["original/*"])
    self.model = OPF(model=pPath(checkpoint) / "original", device="cuda")
    self.model.redact("Synthetic warm-up text.")
    volume.commit()

  @modal.method()
  def detect(self, texts: list[str]) -> list[list[dict]]:
    if len(texts) > 40 or sum(map(len, texts)) > 200000:
      raise ValueError("Document exceeds prototype text limit")
    result = []
    for text in texts:
      if not text.strip():
        result.append([])
        continue
      prediction = self.model.redact(text).to_dict()
      if prediction.get("warning") or prediction["text"] != text:
        raise ValueError("Model text offsets did not match the input")
      result.append(prediction["detected_spans"])
    return result


@app.local_entrypoint()
def smoke():
  result = PrivacyFilter().detect.remote([
    "Synthetic test: Contact Alice Example at alice@example.com or +41 79 555 01 23."
  ])
  print({"span_count": len(result[0]), "labels": sorted({s["label"] for s in result[0]})})
