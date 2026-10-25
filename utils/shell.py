"""Shell and file manager helpers."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def open_in_file_explorer(path: Path) -> None:
    """Open a directory or reveal a file in the platform file manager.

    Windows uses Explorer, macOS uses Finder (``open``), and Linux falls back
    to ``xdg-open``. Paths with spaces or non-ASCII characters are passed
    without shell quoting. Raises ``FileNotFoundError`` for missing paths and
    ``RuntimeError`` when the platform command fails to launch.
    """
    if not path.exists():
        raise FileNotFoundError(f"路径不存在: {path}")

    if sys.platform == "win32":
        _open_windows(path)
    elif sys.platform == "darwin":
        _open_macos(path)
    else:
        _open_linux(path)


def _open_windows(path: Path) -> None:
    if path.is_dir():
        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    try:
        subprocess.Popen(["explorer", "/select,", str(path)])  # noqa: S603
    except OSError as exc:
        raise RuntimeError(f"无法打开文件管理器: {exc}") from exc


def _open_macos(path: Path) -> None:
    command = ["open", str(path)] if path.is_dir() else ["open", "-R", str(path)]
    try:
        subprocess.Popen(command)  # noqa: S603
    except OSError as exc:
        raise RuntimeError(f"无法打开 Finder: {exc}") from exc


def _open_linux(path: Path) -> None:
    try:
        subprocess.Popen(["xdg-open", str(path)])  # noqa: S603,S607
    except OSError as exc:
        raise RuntimeError(f"无法打开文件管理器: {exc}") from exc
