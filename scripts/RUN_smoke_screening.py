# scripts/RUN_smoke_screening.py
# Rationale: verify the real local HTTP-to-Modal CPU path with synthetic text.
# Assumptions: the local service and deployed screening worker are available.
# Constraints: uses Modal compute, never writes screening memory, deletes its session.

import httpx
import pymupdf


def main():
  with pymupdf.open() as doc:
    page = doc.new_page()
    page.insert_text((50, 70), "SYNTHETIC REVIEW CHECK", fontsize=18)
    page.insert_text((50, 120), "William Waeber, juge. Contact: alice@example.com.")
    payload = doc.tobytes()
  with httpx.Client(base_url="http://127.0.0.1:8766", headers={"X-Lexmini-Client": "review"}, timeout=900) as client:
    client.get("/health").raise_for_status()
    upload = client.post("/api/documents", params={"filename": "synthetic_cpu_check.pdf"}, content=payload)
    upload.raise_for_status()
    identifier = upload.json()["document_id"]
    try:
      result = client.post(f"/api/documents/{identifier}/analyse", json={"languages": ["fr"], "use_layout": True})
      result.raise_for_status()
      data = result.json()
      assert any(f["field_type"] == "email" for f in data["findings"])
      assert any("spacy/" in f["detector"] for f in data["findings"])
      source = client.get(f"/api/documents/{identifier}/pages/1/text").json()
      assert source["regions"]
      print({"processing": data["processing"], "findings": len(data["findings"]),
        "regions": len(source["regions"]), "status": "live HTTP and Modal CPU check passed"})
    finally:
      client.delete(f"/api/documents/{identifier}")


if __name__ == "__main__":
  main()
