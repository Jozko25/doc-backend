"""Ensure project sources are importable when running locally."""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent
src_path = project_root / "src"
if src_path.exists() and str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))
