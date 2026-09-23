# src/lexmini/api_access.py
"""Fixed demonstration deadline; restarting the service never extends access."""
from datetime import datetime, timezone

# Thirty days from the owner's request. Never store the API key in source code.
OPENAI_EXPIRES_AT = datetime(2026, 10, 23, 13, 52, 45, tzinfo=timezone.utc)


def require_openai_access():
  if datetime.now(timezone.utc) >= OPENAI_EXPIRES_AT:
    raise ValueError('OpenAI access for this demonstration expired on 23 October 2026 at 13:52:45 UTC.')


async def guard_openai_request(request):
  # The HTTP hook also checks SDK retries and subsequent agent requests.
  require_openai_access()
