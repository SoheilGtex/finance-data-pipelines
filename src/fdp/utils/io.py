"""Filesystem helpers bound to explicit runtime paths."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..config import RuntimePaths


def ensure_dirs(paths: RuntimePaths) -> None:
    for path in (paths.output_dir, paths.raw_dir, paths.normalized_dir, paths.database_path.parent):
        path.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
