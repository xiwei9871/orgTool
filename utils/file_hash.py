"""File hashing helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path


def compute_file_hash(path: Path, algorithm: str = "sha256") -> str:
    """Compute a stable digest for a file."""
    hasher = hashlib.new(algorithm)
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()
