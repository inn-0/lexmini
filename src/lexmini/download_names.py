# src/lexmini/download_names.py
"""Keep the source name in downloads, with a Lexmini prefix."""
import re
from urllib.parse import quote


def download_name(source: str, extension: str):
  name=source.replace('\\','/').rsplit('/',1)[-1]
  stem=re.sub(r'\.pdf$', '', name, flags=re.IGNORECASE)
  stem=re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]', '_', stem).strip(' .') or 'document'
  return f'lexmini_{stem[:180]}.{extension}'


def attachment(source: str, extension: str):
  return f"attachment; filename=\"lexmini-document.{extension}\"; filename*=UTF-8''{quote(download_name(source,extension),safe='')}"
