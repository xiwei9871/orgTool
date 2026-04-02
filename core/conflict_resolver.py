"""Conflict-safe destination naming."""

from __future__ import annotations

from pathlib import Path


def resolve_conflict_path(target_path: Path) -> Path:
    """Return a non-conflicting destination path without overwriting files."""
    if not target_path.exists():
        return target_path

    stem = target_path.stem
    suffix = target_path.suffix
    parent = target_path.parent
    index = 1

    while True:
        candidate = parent / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
        index += 1
