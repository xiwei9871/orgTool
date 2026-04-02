"""Windows file attribute helpers with graceful fallback behavior."""

from __future__ import annotations

from pathlib import Path

FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4


def get_file_attributes(path: Path) -> int:
    """Return Windows file attributes when available, otherwise 0."""
    try:
        stat_result = path.stat()
    except OSError:
        return 0

    return int(getattr(stat_result, "st_file_attributes", 0))


def is_hidden(path: Path) -> bool:
    """Return whether a file should be treated as hidden."""
    if path.name.startswith("."):
        return True
    return bool(get_file_attributes(path) & FILE_ATTRIBUTE_HIDDEN)


def is_system(path: Path) -> bool:
    """Return whether a file should be treated as a system file."""
    return bool(get_file_attributes(path) & FILE_ATTRIBUTE_SYSTEM)
