import sys
from pathlib import Path

# The shared `contracts` package lives at the repo root (owned by both developers).
_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.append(_REPO_ROOT)
