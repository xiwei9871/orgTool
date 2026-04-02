"""Common model primitives shared across modules."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PathInfo:
    """Basic path metadata used across scans and previews."""

    name: str
    path: str
    extension: str
