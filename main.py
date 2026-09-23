# main.py
# Rationale: Replit's default Run action must start the real review service.
# Assumptions: the launcher installs locked dependencies with uv.
# Constraints: secrets stay in the environment; no extra server process.
import os
from pathlib import Path as pPath

os.chdir(pPath(__file__).resolve().parent)
os.execvp('bash',['bash','scripts/RUN_replit.sh'])
