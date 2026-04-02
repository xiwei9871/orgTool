"""Windows-specific helpers."""

from __future__ import annotations

import ctypes
from pathlib import Path
from uuid import UUID


def resolve_desktop_directory() -> Path:
    """Resolve the current user's desktop directory on Windows.

    The Windows Known Folder API is tried first. If that fails, fall back to
    common desktop-like locations. The return value may still be non-existent,
    and callers should validate it before use.
    """
    known_folder = _get_known_folder_path("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}")
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


def _get_known_folder_path(folder_id: str) -> str | None:
    """Return a Windows known-folder path if available."""
    try:
        shell32 = ctypes.windll.shell32
        ole32 = ctypes.windll.ole32
    except AttributeError:
        return None

    guid = UUID(folder_id)

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_ulong),
            ("Data2", ctypes.c_ushort),
            ("Data3", ctypes.c_ushort),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    data4 = (ctypes.c_ubyte * 8)(*guid.bytes[8:])
    folder_guid = GUID(
        guid.time_low,
        guid.time_mid,
        guid.time_hi_version,
        data4,
    )
    out_path = ctypes.c_wchar_p()
    result = shell32.SHGetKnownFolderPath(
        ctypes.byref(folder_guid),
        0,
        None,
        ctypes.byref(out_path),
    )
    if result != 0:
        return None

    try:
        return out_path.value
    finally:
        ole32.CoTaskMemFree(out_path)
