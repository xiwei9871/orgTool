"""Models for desktop scanning and preview construction."""

from __future__ import annotations

from dataclasses import dataclass

from models.common import PathInfo


@dataclass(slots=True)
class DesktopItem(PathInfo):
    """A scanned top-level desktop entry."""

    item_type: str
    is_skipped: bool = False
    skip_reason: str = ""


@dataclass(slots=True)
class PreviewItem:
    """A preview row shown before execution."""

    name: str
    source_path: str
    file_type: str
    suggested_category: str
    target_path: str
    confidence: float
    reason: str
    is_skipped: bool
    skip_reason: str
    subcategory: str = ""
