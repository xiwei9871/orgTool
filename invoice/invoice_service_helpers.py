"""Helper functions for invoice service orchestration."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def modified_time_for(path: Path) -> datetime:
    """Return the filesystem modified timestamp as a datetime."""
    return datetime.fromtimestamp(path.stat().st_mtime)
