from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
src_text = str(SRC)
sys.path = [entry for entry in sys.path if entry != src_text]
sys.path.insert(0, src_text)
