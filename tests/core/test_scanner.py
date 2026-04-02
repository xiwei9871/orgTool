"""Tests for top-level desktop scanning."""

from __future__ import annotations

from pathlib import Path

from core.scanner import DesktopScanner


def test_scanner_enumerates_top_level_desktop_items(tmp_path: Path) -> None:
    """The scanner should include files, folders, and shortcuts at the top level."""
    (tmp_path / "report.pdf").write_text("demo", encoding="utf-8")
    (tmp_path / "app.lnk").write_text("shortcut", encoding="utf-8")
    (tmp_path / "资料夹").mkdir()
    nested_dir = tmp_path / "nested"
    nested_dir.mkdir()
    (nested_dir / "inside.txt").write_text("nested", encoding="utf-8")

    scanner = DesktopScanner()
    items = scanner.scan(
        tmp_path,
        whitelist_names=set(),
        whitelist_extensions=set(),
        skip_hidden=False,
        skip_system=False,
    )

    names = {item.name for item in items}
    assert "report.pdf" in names
    assert "app.lnk" in names
    assert "资料夹" in names
    assert "inside.txt" not in names


def test_scanner_marks_skipped_entries_with_reason(tmp_path: Path) -> None:
    """Skipped paths should remain visible in results with a skip reason."""
    (tmp_path / "desktop.ini").write_text("shell", encoding="utf-8")
    (tmp_path / "保留.txt").write_text("demo", encoding="utf-8")

    scanner = DesktopScanner()
    items = scanner.scan(
        tmp_path,
        whitelist_names={"保留.txt"},
        whitelist_extensions=set(),
        skip_hidden=False,
        skip_system=False,
    )

    by_name = {item.name: item for item in items}
    assert by_name["desktop.ini"].is_skipped is True
    assert by_name["desktop.ini"].skip_reason == "desktop_ini"
    assert by_name["保留.txt"].is_skipped is True
    assert by_name["保留.txt"].skip_reason == "whitelist_name"


def test_scanner_detects_item_types(tmp_path: Path) -> None:
    """The scanner should label files, folders, and shortcuts distinctly."""
    (tmp_path / "installer.msi").write_text("demo", encoding="utf-8")
    (tmp_path / "tool.lnk").write_text("shortcut", encoding="utf-8")
    (tmp_path / "项目").mkdir()

    scanner = DesktopScanner()
    items = scanner.scan(
        tmp_path,
        whitelist_names=set(),
        whitelist_extensions=set(),
        skip_hidden=False,
        skip_system=False,
    )

    by_name = {item.name: item for item in items}
    assert by_name["installer.msi"].item_type == "file"
    assert by_name["tool.lnk"].item_type == "shortcut"
    assert by_name["项目"].item_type == "folder"
