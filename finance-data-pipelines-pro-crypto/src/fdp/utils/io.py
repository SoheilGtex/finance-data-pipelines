from __future__ import annotations

from .config import DATA_DIR, RAW_DIR, CLEAN_DIR

def ensure_dirs():
    for p in (DATA_DIR, RAW_DIR, CLEAN_DIR):
        p.mkdir(parents=True, exist_ok=True)
