# src/lexmini/main.py
"""Local API and review webpage. The model runs in the user's Modal workspace."""

import asyncio
import json
from contextlib import asynccontextmanager, suppress

import httpx
import logfire
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi_mcp import FastApiMCP
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import _config, pdf, rules, services, quality, paragraphs
from .sharing import router as sharing_router
from .governance_routes import router as governance_router
from .governance_demo import DemoDenied
from .schemas import Context, DocumentReview, ExportRequest, Health, LearnRequest, RestoreReviewRequest, QualityRequest

logfire.configure(send_to_logfire=False, console=False)


@asynccontextmanager
async def lifespan(app):
  async def cleanup():
    while True:
      await asyncio.sleep(30)
      services.store.cleanup()
  task = asyncio.create_task(cleanup())
  yield
  task.cancel()
  with suppress(asyncio.CancelledError):
    await task


app = FastAPI(title="Lexmini", version="0.1.0", lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver", "*.replit.dev", "*.replit.app"])
app.add_middleware(CORSMiddleware,
  allow_origin_regex=r"(?:http://(?:localhost|127\.0\.0\.1):8766|chrome-extension://[a-p]{32})",
  allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type", "X-Lexmini-Client", "Authorization"])


@app.middleware("http")
async def browser_boundary(request: Request, call_next):
  # Browser mutation requests must preflight. Ordinary web pages cannot post documents.
  if request.method in {"POST", "DELETE"} and request.url.path.startswith("/api/"):
    if request.headers.get("x-lexmini-client") != "review":
      return JSONResponse({"detail": "Open the Lexmini review screen to use this endpoint"}, status_code=403)
  response = await call_next(request)
  response.headers["Cache-Control"] = "no-store"
  response.headers["X-Content-Type-Options"] = "nosniff"
  response.headers["Referrer-Policy"] = "no-referrer"
  return response


@app.exception_handler(DemoDenied)
async def demo_denied(request, exc):
  return JSONResponse({"detail": exc.message}, status_code=exc.status)


@app.exception_handler(ValueError)
async def invalid_input(request, exc):
  return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(KeyError)
async def expired(request, exc):
  return JSONResponse({"detail": "Document expired or was closed. Open the PDF again."}, status_code=404)


@app.get("/health", response_model=Health, tags=["tools"], operation_id="lexmini_health")
def health():
  return Health()


@app.get("/api/policy", tags=["tools"], operation_id="lexmini_policy")
def policy():
  return {"sensitivity_levels": ["public", "personal-private", "professional-secrecy"],
    "concepts": rules.CONCEPTS, "context_help": "Rule-based suggestions for keeping dates and amounts; selections stay unchanged."}


@app.get("/")
def home():
  return RedirectResponse("/assets/review.html")


@app.post("/api/documents", response_model=DocumentReview)
async def upload(request: Request, filename: str = "document.pdf"):
  chunks, size = [], 0
  async for chunk in request.stream():
    size += len(chunk)
    if size > _config.MAX_BYTES:
      raise HTTPException(413, "Choose a PDF smaller than 20 MiB")
    chunks.append(chunk)
  try:
    return await run_in_threadpool(services.store.create, b"".join(chunks), filename)
  except (ValueError, KeyError):
    raise
  except Exception:
    raise HTTPException(400, "The PDF could not be read. Check that it is valid and unlocked.") from None


@app.get("/api/documents/{document_id}", response_model=DocumentReview, tags=["tools"], operation_id="lexmini_get_review")
def review(document_id: str):
  session = services.store.get(document_id)
  with session.lock:
    return session.review.model_copy(deep=True)


@app.get("/api/documents/{document_id}/source")
def recovery_source(document_id: str):
  return Response(services.store.get(document_id).payload, media_type="application/pdf")


@app.post("/api/documents/{document_id}/restore", response_model=DocumentReview)
def restore_review(document_id: str, request: RestoreReviewRequest):
  return services.restore_review(document_id, request)


@app.post("/api/documents/{document_id}/analyse", response_model=DocumentReview, tags=["tools"], operation_id="lexmini_analyse_document")
def analyse(document_id: str, context: Context):
  try:
    return services.analyse(document_id, context)
  except (ValueError, KeyError):
    raise
  except Exception:
    raise HTTPException(503, "Document detection failed or timed out. Your document is still open; retry detection.") from None


@app.get("/api/documents/{document_id}/pages/{number}")
def page(document_id: str, number: int):
  return Response(pdf.page_png(services.store.get(document_id).payload, number), media_type="image/png")


@app.get("/api/documents/{document_id}/pages/{number}/text")
def page_text(document_id: str, number: int):
  session = services.store.get(document_id)
  with session.lock:
    if not 1 <= number <= len(session.extracted.pages):
      raise ValueError("Page does not exist")
    page = session.extracted.pages[number - 1]
    return {"text": page.text, "boxes": page.boxes,
      "paragraphs": [p.model_dump(exclude={"offsets"}) for p in paragraphs.build(page, session.layout_regions)],
      "regions": [r.model_dump() for r in session.layout_regions if r.page_number == number]}


@app.post("/api/documents/{document_id}/learn", response_model=DocumentReview)
def learn_example(document_id: str, example: LearnRequest):
  return services.learn(document_id, example)


@app.post("/api/documents/{document_id}/quality", response_model=DocumentReview)
def quality_review(document_id: str, request: QualityRequest):
  return services.quality_review(document_id, request)


@app.post("/api/documents/{document_id}/export")
def export(document_id: str, selection: ExportRequest):
  payload = services.export(document_id, selection)
  extension = "pdf" if selection.format == "pdf" else "txt"
  return Response(payload, media_type="application/pdf" if extension == "pdf" else "text/plain; charset=utf-8",
    headers={"Content-Disposition": f'attachment; filename="lexmini-reviewed.{extension}"'})


@app.delete("/api/documents/{document_id}")
def close(document_id: str):
  services.store.remove(document_id)
  return {"closed": True}


@app.get("/api/documents/{document_id}/keys")
def token_keys(document_id: str):
  session = services.store.get(document_id)
  with session.lock:
    return {"document_id": document_id, "scope": "document", "keys": dict(session.tokens.values)}


@app.get("/api/demo")
def demo():
  return FileResponse(_config.ROOT / "data/TEST_legal_demo.pdf", media_type="application/pdf")


@app.get("/api/samples")
def samples():
  catalogue = _config.ROOT / "data/reference/sample_catalogue.json"
  return json.loads(catalogue.read_text()) if catalogue.exists() else []


@app.get("/api/samples/{sample_id}")
def sample(sample_id: str):
  item = next((item for item in samples() if item["id"] == sample_id), None)
  if item is None:
    raise HTTPException(404, "Sample not found")
  return FileResponse(_config.ROOT / "data/reference" / item["file"], media_type="application/pdf")


@app.get("/api/quality")
def quality_examples():
  return quality.catalogue()


@app.post("/api/quality/{sample_id}", response_model=DocumentReview)
def quality_example(sample_id: str, context: Context):
  return quality.load(sample_id, context)


# Unfinished synthetic walkthrough is archived until ready for presentation.
# app.include_router(governance_router)
app.include_router(sharing_router)


mcp = FastApiMCP(app, name="Lexmini", include_tags=["tools"],
  http_client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
    base_url="http://testserver", headers={"X-Lexmini-Client": "review"}, timeout=650))
mcp.mount_http(mount_path="/mcp")
app.mount("/assets", StaticFiles(directory=str(_config.ROOT / "extension")), name="assets")
