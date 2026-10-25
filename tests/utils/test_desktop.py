"""Tests for cross-platform desktop directory resolution."""

from __future__ import annotations

import sys
from pathlib import Path

import utils.desktop as desktop


def test_windows_desktop_uses_known_folder(tmp_path: Path, monkeypatch) -> None:
    """Windows resolution should prefer the Known Folder API result."""
    monkeypatch.setattr(desktop.sys, "platform", "win32")
    monkeypatch.setattr(
        desktop, "get_known_folder_path", lambda _id: str(tmp_path / "WinDesktop")
    )

    assert desktop.resolve_desktop_directory() == tmp_path / "WinDesktop"


def test_windows_desktop_falls_back_to_home_desktop(
    tmp_path: Path, monkeypatch
) -> None:
    """When the Known Folder API fails, Windows falls back to ~/Desktop."""
    home = tmp_path / "home"
    (home / "Desktop").mkdir(parents=True)
    monkeypatch.setattr(desktop.sys, "platform", "win32")
    monkeypatch.setattr(desktop, "get_known_folder_path", lambda _id: None)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    assert desktop.resolve_desktop_directory() == home / "Desktop"


def test_macos_desktop_prefers_home_desktop(tmp_path: Path, monkeypatch) -> None:
    """macOS resolution returns ~/Desktop when it exists."""
    home = tmp_path / "home"
    (home / "Desktop").mkdir(parents=True)
    icloud = home / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "Desktop"
    icloud.mkdir(parents=True)
    monkeypatch.setattr(desktop.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    assert desktop.resolve_desktop_directory() == home / "Desktop"


def test_macos_desktop_uses_icloud_desktop_when_home_missing(
    tmp_path: Path, monkeypatch
) -> None:
    """macOS falls back to the iCloud Drive desktop directory."""
    home = tmp_path / "home"
    icloud = home / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "Desktop"
    icloud.mkdir(parents=True)
    monkeypatch.setattr(desktop.sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    assert desktop.resolve_desktop_directory() == icloud


def test_xdg_desktop_uses_xdg_user_dir(tmp_path: Path, monkeypatch) -> None:
    """Linux resolution should honor xdg-user-dir output."""
    monkeypatch.setattr(desktop.sys, "platform", "linux")

    class _Result:
        returncode = 0
        stdout = str(tmp_path / "定制桌面") + "\n"
        stderr = ""

    monkeypatch.setattr(desktop.subprocess, "run", lambda *a, **k: _Result())

    assert desktop.resolve_desktop_directory() == tmp_path / "定制桌面"


def test_xdg_desktop_parses_user_dirs_config(tmp_path: Path, monkeypatch) -> None:
    """The user-dirs.dirs file is used when xdg-user-dir is unavailable."""
    home = tmp_path / "home"
    xdg_config = tmp_path / "xdg-config"
    xdg_config.mkdir(parents=True)
    (xdg_config / "user-dirs.dirs").write_text(
        'XDG_DESKTOP_DIR="$HOME/Desk Top"\n', encoding="utf-8"
    )
    monkeypatch.setattr(desktop.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_config))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    def _raise(*args, **kwargs):
        raise FileNotFoundError("xdg-user-dir missing")

    monkeypatch.setattr(desktop.subprocess, "run", _raise)

    assert desktop.resolve_desktop_directory() == home / "Desk Top"


def test_xdg_desktop_falls_back_to_home(tmp_path: Path, monkeypatch) -> None:
    """Without XDG config the fallback is ~/Desktop."""
    home = tmp_path / "home"
    (home / "Desktop").mkdir(parents=True)
    monkeypatch.setattr(desktop.sys, "platform", "linux")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty-config"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    def _raise(*args, **kwargs):
        raise FileNotFoundError("xdg-user-dir missing")

    monkeypatch.setattr(desktop.subprocess, "run", _raise)

    assert desktop.resolve_desktop_directory() == home / "Desktop"


def test_resolve_desktop_directory_returns_path_on_this_platform() -> None:
    """Smoke: resolution always returns a Path without raising."""
    if sys.platform not in {"win32", "darwin", "linux"}:
        return
    result = desktop.resolve_desktop_directory()
    assert isinstance(result, Path)
