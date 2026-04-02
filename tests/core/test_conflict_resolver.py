"""Tests for safe destination name resolution."""

from __future__ import annotations

from pathlib import Path

from core.conflict_resolver import resolve_conflict_path


def test_resolve_conflict_path_appends_incrementing_suffix(tmp_path: Path) -> None:
    """Conflicting file names should receive numbered suffixes."""
    target_dir = tmp_path / "archive"
    target_dir.mkdir()
    (target_dir / "文件.pdf").write_text("a", encoding="utf-8")
    (target_dir / "文件 (1).pdf").write_text("b", encoding="utf-8")

    resolved = resolve_conflict_path(target_dir / "文件.pdf")

    assert resolved == target_dir / "文件 (2).pdf"
