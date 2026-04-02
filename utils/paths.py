"""Helpers for resolving runtime storage paths."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class RuntimePaths:
    """All runtime paths rooted in the user's APPDATA directory."""

    root: Path
    config_file: Path
    logs_dir: Path
    tasks_dir: Path
    invoice_metadata_dir: Path

    @classmethod
    def from_env(cls, app_name: str) -> "RuntimePaths":
        """Build runtime paths under the APPDATA directory and create them."""
        appdata = os.environ.get("APPDATA")
        candidates = []
        if appdata:
            candidates.append(Path(appdata).expanduser() / app_name)
        else:
            candidates.append(Path.home() / "AppData" / "Roaming" / app_name)
        candidates.append(Path.cwd() / ".runtime" / app_name)

        last_error: OSError | None = None
        for root in candidates:
            paths = cls(
                root=root,
                config_file=root / "config.json",
                logs_dir=root / "logs",
                tasks_dir=root / "tasks",
                invoice_metadata_dir=root / "invoice_metadata",
            )
            try:
                paths.ensure_dirs()
                probe_file = paths.root / ".write_probe"
                probe_file.write_text("ok", encoding="utf-8")
                probe_file.unlink(missing_ok=True)
                return paths
            except OSError as exc:
                last_error = exc
                continue

        if last_error is not None:
            raise last_error

        raise RuntimeError("Unable to resolve runtime paths")

    def ensure_dirs(self) -> None:
        """Create runtime directories if they do not already exist."""
        self.root.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.invoice_metadata_dir.mkdir(parents=True, exist_ok=True)
