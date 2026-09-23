# src/lexmini/_config.py
"""Environment-backed settings; never expose credential values to the browser."""

import os
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
from pathlib import Path as pPath

ROOT = pPath(__file__).resolve().parents[2]
API_KEY_OPENAI = os.environ.get("OPENAI_API_KEY", "")
HF_TOKEN = os.environ.get("HF_TOKEN", "")
MODAL_APP = "demokratis-lexmini-privacy"
MODAL_CLASS = "PrivacyFilter"
MODEL_REVISION = "7ffa9a043d54d1be65afb281eddf0ffbe629385b"
OPF_REVISION = "f7f00ca7fb869683eb732c010299d901457f19c3"
PORT = 8766
MAX_BYTES = 20 * 1024 * 1024
MAX_PAGES = 40
SESSION_SECONDS = 1800
MAX_SESSIONS = 8
ORGANISATION_ID = os.environ.get("LEXMINI_ORGANISATION_ID", "local-organisation")
SCREENING_APP = "demokratis-lexmini-screening"
SCREENING_CLASS = "DocumentScreening"
NEON_AUTH_BASE_URL = os.environ.get("NEON_AUTH_BASE_URL", "")
QUALITY_MODEL = os.environ.get('LEXMINI_QUALITY_MODEL', 'gpt-4.1-mini')
