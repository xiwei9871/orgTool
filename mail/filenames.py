"""Filename sanitization and path-traversal protection."""

from __future__ import annotations

import re
from pathlib import Path

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
_MAX_FILENAME_BYTES = 200


def sanitize_filename(name: str, fallback: str = "attachment") -> str:
    """Return a filesystem-safe filename on both Windows and macOS.

    Strips path separators, traversal segments, control characters, and
    reserved Windows device names. Never returns a name containing a path.
    """
    name = name.replace("\\", "/")
    name = name.rsplit("/", 1)[-1]
    name = _INVALID_CHARS.sub("_", name)
    name = name.strip().strip(".")
    if not name:
        name = fallback
    stem, dot, suffix = name.rpartition(".")
    if not stem:
        stem, dot, suffix = name, "", ""
    if stem.casefold() in _RESERVED_NAMES:
        stem = f"_{stem}"
    name = stem + (dot + suffix if dot else "")
    while len(name.encode("utf-8")) > _MAX_FILENAME_BYTES:
        name = name[: len(name) - 1]
        name = name.rstrip(". ")
    if not name or name in {".", ".."}:
        name = fallback
    return name


def safe_join(root: Path, *parts: str) -> Path:
    """Join ``parts`` under ``root`` and guarantee the result stays inside it."""
    resolved_root = root.resolve()
    candidate = resolved_root.joinpath(*parts).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"路径穿越被拒绝: {candidate}") from exc
    return candidate
