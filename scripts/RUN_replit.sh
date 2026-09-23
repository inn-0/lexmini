#!/usr/bin/env bash
# scripts/RUN_replit.sh
# Rationale: run the review service on Replit using server-side secrets.
# Assumptions: uv is available; managed inference is configured separately.
# Constraints: one process while grants and sessions remain in memory.
set -euo pipefail
export UV_CACHE_DIR="$HOME/.cache/uv"
uv sync --frozen
exec .venv/bin/python3 -m uvicorn lexmini.main:app --host 0.0.0.0 --port 8000 --no-access-log
