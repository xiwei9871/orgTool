"""Shell and explorer helpers."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def open_in_file_explorer(path: Path) -> None:
    """Open a directory or file in the platform file explorer."""
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    subprocess.Popen(["xdg-open", str(path)])  # noqa: S603,S607
