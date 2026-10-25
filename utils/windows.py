"""Windows-specific helpers."""

from __future__ import annotations

import ctypes
from uuid import UUID


def get_known_folder_path(folder_id: str) -> str | None:
    """Return a Windows known-folder path if available.

    Returns ``None`` on non-Windows platforms or when the API call fails.
    """
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
