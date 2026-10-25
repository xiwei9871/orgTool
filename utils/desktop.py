"""Cross-platform desktop directory resolution."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from utils.windows import get_known_folder_path

_DESKTOP_KNOWN_FOLDER_ID = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"


def resolve_desktop_directory() -> Path:
    """Resolve the current user's desktop directory on any platform.

    Windows uses the Known Folder API first; macOS prefers ``~/Desktop``
    then the iCloud Drive desktop; Linux follows ``xdg-user-dirs``. The
    returned path may not exist — callers should validate before use.
    """
    if sys.platform == "win32":
        return _resolve_windows_desktop()
    if sys.platform == "darwin":
        return _resolve_macos_desktop()
    return _resolve_xdg_desktop()


def _resolve_windows_desktop() -> Path:
    known_folder = get_known_folder_path(_DESKTOP_KNOWN_FOLDER_ID)
    if known_folder:
        return Path(known_folder)

    candidates = [
        Path.home() / "Desktop",
        Path.home() / "OneDrive" / "Desktop",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _resolve_macos_desktop() -> Path:
    candidates = [
        Path.home() / "Desktop",
        Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "Desktop",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _resolve_xdg_desktop() -> Path:
    configured = _xdg_user_dir("DESKTOP")
    if configured is not None:
        return configured

    candidate = Path.home() / "Desktop"
    if candidate.exists():
        return candidate
    return candidate


def _xdg_user_dir(name: str) -> Path | None:
    """Return an XDG user directory such as ``DESKTOP`` if configured."""
    try:
        result = subprocess.run(
            ["xdg-user-dir", name],  # noqa: S603,S607
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        value = result.stdout.strip()
        if result.returncode == 0 and value and value != str(Path.home()):
            return Path(value)
    except (OSError, subprocess.SubprocessError):
        pass

    config_file = Path(
        os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
    ) / "user-dirs.dirs"
    try:
        content = config_file.read_text(encoding="utf-8")
    except OSError:
        return None

    match = re.search(rf'^XDG_{name}_DIR="?([^"\n]+)"?\s*$', content, re.MULTILINE)
    if not match:
        return None
    raw_value = match.group(1).replace("$HOME", str(Path.home()))
    return Path(raw_value)
