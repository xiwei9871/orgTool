"""Tests for desktop skip filters."""

from __future__ import annotations

from pathlib import Path

from core.filters import should_skip_path


def test_should_skip_path_when_name_is_whitelisted(tmp_path: Path) -> None:
    """Whitelist names should skip matching entries."""
    path = tmp_path / "保留资料.pdf"
    path.write_text("demo", encoding="utf-8")

    should_skip, reason = should_skip_path(
        path,
        whitelist_names={"保留资料.pdf"},
        whitelist_extensions=set(),
        skip_hidden=False,
        skip_system=False,
    )

    assert should_skip is True
    assert reason == "whitelist_name"


def test_should_skip_path_when_extension_is_whitelisted(tmp_path: Path) -> None:
    """Whitelist extensions should skip matching entries."""
    path = tmp_path / "notes.tmp"
    path.write_text("demo", encoding="utf-8")

    should_skip, reason = should_skip_path(
        path,
        whitelist_names=set(),
        whitelist_extensions={".tmp"},
        skip_hidden=False,
        skip_system=False,
    )

    assert should_skip is True
    assert reason == "whitelist_extension"


def test_should_skip_path_for_desktop_ini(tmp_path: Path) -> None:
    """desktop.ini should always be skipped."""
    path = tmp_path / "desktop.ini"
    path.write_text("[.ShellClassInfo]", encoding="utf-8")

    should_skip, reason = should_skip_path(
        path,
        whitelist_names=set(),
        whitelist_extensions=set(),
        skip_hidden=False,
        skip_system=False,
    )

    assert should_skip is True
    assert reason == "desktop_ini"


def test_should_not_skip_normal_file(tmp_path: Path) -> None:
    """Normal files should pass the filter when no rules match."""
    path = tmp_path / "report.pdf"
    path.write_text("demo", encoding="utf-8")

    should_skip, reason = should_skip_path(
        path,
        whitelist_names=set(),
        whitelist_extensions=set(),
        skip_hidden=False,
        skip_system=False,
    )

    assert should_skip is False
    assert reason == ""
