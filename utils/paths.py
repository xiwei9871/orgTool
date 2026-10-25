"""Helpers for resolving runtime storage paths."""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from platformdirs import user_config_dir

RUNTIME_DIR_ENV = "ORGTOOL_RUNTIME_DIR"
MIGRATION_MARKER = ".storage_migration"


@dataclass(slots=True)
class RuntimePaths:
    """All runtime paths rooted in the per-user data directory."""

    root: Path
    config_file: Path
    logs_dir: Path
    tasks_dir: Path
    invoice_metadata_dir: Path

    @classmethod
    def from_root(cls, root: Path) -> "RuntimePaths":
        """Build runtime paths under an explicit root directory."""
        return cls(
            root=root,
            config_file=root / "config.json",
            logs_dir=root / "logs",
            tasks_dir=root / "tasks",
            invoice_metadata_dir=root / "invoice_metadata",
        )

    @classmethod
    def from_env(cls, app_name: str) -> "RuntimePaths":
        """Build runtime paths for the current platform and create them.

        Resolution order:
        1. ``ORGTOOL_RUNTIME_DIR`` environment override (tests, portable mode).
        2. Platform per-user config directory:
           Windows ``%APPDATA%/<app>``, macOS ``~/Library/Application
           Support/<app>``, Linux ``~/.config/<app>``.
        3. ``<cwd>/.runtime/<app>`` as a last-resort writable fallback.

        After the primary platform directory is resolved, legacy storage
        locations are migrated automatically (see ``migrate_legacy_storage``).
        """
        primary_candidates = _primary_root_candidates(app_name)
        candidates = primary_candidates + [Path.cwd() / ".runtime" / app_name]

        last_error: OSError | None = None
        for index, root in enumerate(candidates):
            paths = cls.from_root(root)
            try:
                paths.ensure_dirs()
                probe_file = paths.root / ".write_probe"
                probe_file.write_text("ok", encoding="utf-8")
                probe_file.unlink(missing_ok=True)
                if index < len(primary_candidates):
                    migrate_legacy_storage(paths, app_name)
                return paths
            except OSError as exc:
                last_error = exc
                continue

        if last_error is not None:
            raise last_error

        raise RuntimeError("Unable to resolve runtime paths")

    @property
    def mail_sync_db(self) -> Path:
        """SQLite database file for mail synchronization state."""
        return self.root / "mail_sync.db"

    @property
    def mail_dir(self) -> Path:
        """Directory holding mail sync state files."""
        return self.root / "mail"

    def ensure_dirs(self) -> None:
        """Create runtime directories if they do not already exist."""
        self.root.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.invoice_metadata_dir.mkdir(parents=True, exist_ok=True)


def _primary_root_candidates(app_name: str) -> list[Path]:
    """Return platform-native storage roots in preference order."""
    override = os.environ.get(RUNTIME_DIR_ENV, "").strip()
    if override:
        return [Path(override).expanduser()]
    return [Path(user_config_dir(app_name, roaming=True))]


def _legacy_root_candidates(app_name: str) -> list[Path]:
    """Return storage roots used by older application versions."""
    candidates = [Path.cwd() / ".runtime" / app_name]
    if sys.platform != "win32":
        # Pre-platformdirs fallback used a Windows-style path on every OS.
        candidates.append(Path.home() / "AppData" / "Roaming" / app_name)
    return candidates


def migrate_legacy_storage(paths: RuntimePaths, app_name: str) -> Path | None:
    """Copy legacy per-user storage into the platform directory once.

    The migration only runs when the new config file does not yet exist, so
    it is safe to run repeatedly and never overwrites user modifications.
    The legacy directory is left untouched as the pre-migration backup, and a
    ``.storage_migration`` marker records what was copied.
    """
    if paths.config_file.exists():
        return None

    for legacy_root in _legacy_root_candidates(app_name):
        try:
            resolved_legacy = legacy_root.resolve()
            resolved_new = paths.root.resolve()
        except OSError:
            continue
        if resolved_legacy == resolved_new:
            continue
        legacy_config = legacy_root / "config.json"
        if not legacy_config.is_file():
            continue

        copied_files: list[str] = []
        try:
            for source in sorted(legacy_root.rglob("*")):
                if source.is_dir():
                    continue
                relative = source.relative_to(legacy_root)
                target = paths.root / relative
                if target.exists():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                copied_files.append(str(relative))
        except OSError:
            continue

        marker = paths.root / MIGRATION_MARKER
        marker.write_text(
            json.dumps(
                {
                    "migrated_from": str(legacy_root),
                    "migrated_at": datetime.now().isoformat(timespec="seconds"),
                    "files": copied_files,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return legacy_root

    return None
