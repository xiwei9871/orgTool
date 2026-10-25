"""Tests for the cross-platform file manager helper."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import utils.shell as shell


def test_open_in_file_explorer_raises_for_missing_path(tmp_path: Path) -> None:
    """Missing paths should raise a clear FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        shell.open_in_file_explorer(tmp_path / "does-not-exist")


def test_open_directory_on_macos_uses_open_command(
    tmp_path: Path, monkeypatch
) -> None:
    """Directories on macOS should open in Finder via ``open``."""
    calls: list[list[str]] = []

    class _Proc:
        pass

    monkeypatch.setattr(shell.sys, "platform", "darwin")
    monkeypatch.setattr(
        shell.subprocess, "Popen", lambda cmd, *a, **k: calls.append(cmd) or _Proc()
    )

    shell.open_in_file_explorer(tmp_path)

    assert calls == [["open", str(tmp_path)]]


def test_open_file_on_macos_reveals_in_finder(tmp_path: Path, monkeypatch) -> None:
    """Files on macOS should be revealed with ``open -R``."""
    calls: list[list[str]] = []
    target = tmp_path / "发票 文件.pdf"
    target.write_text("x", encoding="utf-8")

    class _Proc:
        pass

    monkeypatch.setattr(shell.sys, "platform", "darwin")
    monkeypatch.setattr(
        shell.subprocess, "Popen", lambda cmd, *a, **k: calls.append(cmd) or _Proc()
    )

    shell.open_in_file_explorer(target)

    assert calls == [["open", "-R", str(target)]]


def test_open_directory_on_windows_uses_startfile(
    tmp_path: Path, monkeypatch
) -> None:
    """Directories on Windows should open via os.startfile."""
    calls: list[str] = []
    monkeypatch.setattr(shell.sys, "platform", "win32")
    monkeypatch.setattr(
        os, "startfile", lambda p: calls.append(p), raising=False
    )

    shell.open_in_file_explorer(tmp_path)

    assert calls == [str(tmp_path)]


def test_open_file_on_windows_uses_explorer_select(
    tmp_path: Path, monkeypatch
) -> None:
    """Files on Windows should be selected via ``explorer /select,``."""
    calls: list[list[str]] = []
    target = tmp_path / "报告 2026.xlsx"
    target.write_text("x", encoding="utf-8")

    class _Proc:
        pass

    monkeypatch.setattr(shell.sys, "platform", "win32")
    monkeypatch.setattr(
        shell.subprocess, "Popen", lambda cmd, *a, **k: calls.append(cmd) or _Proc()
    )

    shell.open_in_file_explorer(target)

    assert calls == [["explorer", "/select,", str(target)]]


def test_open_on_linux_uses_xdg_open(tmp_path: Path, monkeypatch) -> None:
    """Linux should fall back to xdg-open."""
    calls: list[list[str]] = []

    class _Proc:
        pass

    monkeypatch.setattr(shell.sys, "platform", "linux")
    monkeypatch.setattr(
        shell.subprocess, "Popen", lambda cmd, *a, **k: calls.append(cmd) or _Proc()
    )

    shell.open_in_file_explorer(tmp_path)

    assert calls == [["xdg-open", str(tmp_path)]]


def test_missing_platform_command_raises_runtime_error(
    tmp_path: Path, monkeypatch
) -> None:
    """A missing platform binary should surface as RuntimeError."""

    def _raise(*args, **kwargs):
        raise FileNotFoundError("open not found")

    monkeypatch.setattr(shell.sys, "platform", "darwin")
    monkeypatch.setattr(shell.subprocess, "Popen", _raise)

    with pytest.raises(RuntimeError):
        shell.open_in_file_explorer(tmp_path)


def test_chinese_and_space_paths_pass_through_unquoted(
    tmp_path: Path, monkeypatch
) -> None:
    """Paths with spaces and CJK names reach the command unchanged."""
    calls: list[list[str]] = []
    weird = tmp_path / "我的 文件 目录 (v2)"
    weird.mkdir()

    class _Proc:
        pass

    monkeypatch.setattr(shell.sys, "platform", "darwin")
    monkeypatch.setattr(
        shell.subprocess, "Popen", lambda cmd, *a, **k: calls.append(cmd) or _Proc()
    )

    shell.open_in_file_explorer(weird)

    assert calls[0][-1] == str(weird)
