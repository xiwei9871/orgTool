"""Tests for cross-platform runtime paths and legacy migration."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from utils.paths import MIGRATION_MARKER, RuntimePaths

APP = "DesktopSmartOrganizer"


def _make_legacy_runtime(base: Path) -> Path:
    legacy = base / ".runtime" / APP
    legacy.mkdir(parents=True)
    (legacy / "config.json").write_text(
        json.dumps({"general": {"archive_root_name": "迁移的归档"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (legacy / "tasks").mkdir()
    (legacy / "tasks" / "task-1.json").write_text("{}", encoding="utf-8")
    return legacy


def test_from_env_migrates_legacy_runtime_directory(
    tmp_path: Path, monkeypatch
) -> None:
    """A legacy .runtime directory should be migrated to the platform root once."""
    new_root = tmp_path / "platform-root"
    monkeypatch.setenv("ORGTOOL_RUNTIME_DIR", str(new_root))
    monkeypatch.chdir(tmp_path)
    legacy = _make_legacy_runtime(tmp_path)

    paths = RuntimePaths.from_env(APP)

    assert paths.root == new_root
    migrated = json.loads(paths.config_file.read_text(encoding="utf-8"))
    assert migrated["general"]["archive_root_name"] == "迁移的归档"
    assert (paths.tasks_dir / "task-1.json").exists()
    # The legacy directory is left in place as the pre-migration backup.
    assert (legacy / "config.json").exists()
    marker = json.loads((paths.root / MIGRATION_MARKER).read_text(encoding="utf-8"))
    assert marker["migrated_from"] == str(legacy)


def test_migration_is_idempotent_and_preserves_user_changes(
    tmp_path: Path, monkeypatch
) -> None:
    """Running resolution twice must not overwrite user modifications."""
    new_root = tmp_path / "platform-root"
    monkeypatch.setenv("ORGTOOL_RUNTIME_DIR", str(new_root))
    monkeypatch.chdir(tmp_path)
    _make_legacy_runtime(tmp_path)

    paths = RuntimePaths.from_env(APP)
    paths.config_file.write_text(
        json.dumps({"general": {"archive_root_name": "用户修改"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    paths2 = RuntimePaths.from_env(APP)

    current = json.loads(paths2.config_file.read_text(encoding="utf-8"))
    assert current["general"]["archive_root_name"] == "用户修改"


def test_migration_skips_when_target_config_exists(
    tmp_path: Path, monkeypatch
) -> None:
    """An existing platform config must never be overwritten by migration."""
    new_root = tmp_path / "platform-root"
    new_root.mkdir(parents=True)
    (new_root / "config.json").write_text(
        json.dumps({"general": {"archive_root_name": "已存在"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setenv("ORGTOOL_RUNTIME_DIR", str(new_root))
    monkeypatch.chdir(tmp_path)
    _make_legacy_runtime(tmp_path)

    paths = RuntimePaths.from_env(APP)

    current = json.loads(paths.config_file.read_text(encoding="utf-8"))
    assert current["general"]["archive_root_name"] == "已存在"
    assert not (paths.root / MIGRATION_MARKER).exists()


@pytest.mark.skipif(sys.platform == "win32", reason="legacy AppData path is non-Windows")
def test_migration_handles_legacy_appdata_dir_on_posix(
    tmp_path: Path, monkeypatch
) -> None:
    """The old Windows-style fallback dir is migrated on POSIX systems."""
    new_root = tmp_path / "platform-root"
    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    monkeypatch.setenv("ORGTOOL_RUNTIME_DIR", str(new_root))
    # Ensure cwd/.runtime does not exist so AppData legacy is the source.
    monkeypatch.chdir(other_cwd)

    fake_home = tmp_path / "home"
    legacy = fake_home / "AppData" / "Roaming" / APP
    legacy.mkdir(parents=True)
    (legacy / "config.json").write_text(
        json.dumps({"general": {"archive_root_name": "旧Mac归档"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

    paths = RuntimePaths.from_env(APP)

    migrated = json.loads(paths.config_file.read_text(encoding="utf-8"))
    assert migrated["general"]["archive_root_name"] == "旧Mac归档"


def test_mail_sync_paths_are_derived_from_root(tmp_path: Path) -> None:
    """Mail sync database paths should live inside the runtime root."""
    paths = RuntimePaths.from_root(tmp_path)

    assert paths.mail_sync_db == tmp_path / "mail_sync.db"
    assert paths.mail_dir == tmp_path / "mail"
