#!/usr/bin/env bash
# scripts/RUN_server.sh
# Rationale: start the local PDF bridge; Modal credentials stay on this machine.
# Assumptions: uv sync has installed the project and Modal has been deployed.
# Constraints: bind to loopback only; do not log document URLs or contents.
set -euo pipefail
LEXMINI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export UV_CACHE_DIR="$HOME/.cache/uv"
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
cd "$LEXMINI_ROOT"
exec .venv/bin/python3 -m uvicorn lexmini.main:app --host 127.0.0.1 --port 8766 --no-access-log
