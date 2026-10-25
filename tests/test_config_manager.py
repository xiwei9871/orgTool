"""Tests for configuration loading and runtime path management."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from config.manager import ConfigManager
from config.schema import AppConfig
from utils.paths import RuntimePaths


def test_runtime_paths_use_runtime_dir_override(tmp_path: Path, monkeypatch) -> None:
    """ORGTOOL_RUNTIME_DIR should override platform storage for tests."""
    monkeypatch.setenv("ORGTOOL_RUNTIME_DIR", str(tmp_path / "custom-runtime"))

    paths = RuntimePaths.from_env("DesktopSmartOrganizer")

    assert paths.root == tmp_path / "custom-runtime"
    assert paths.config_file == paths.root / "config.json"
    assert paths.logs_dir.is_dir()
    assert paths.tasks_dir.is_dir()


@pytest.mark.skipif(sys.platform != "win32", reason="APPDATA only applies on Windows")
def test_runtime_paths_use_appdata_on_windows(tmp_path: Path, monkeypatch) -> None:
    """Windows runtime paths should live under the APPDATA root."""
    monkeypatch.delenv("ORGTOOL_RUNTIME_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))

    paths = RuntimePaths.from_env("DesktopSmartOrganizer")

    assert paths.root == tmp_path / "DesktopSmartOrganizer"


def test_runtime_paths_use_platform_config_dir(tmp_path: Path, monkeypatch) -> None:
    """The platform config dir should be used when no override is set."""
    monkeypatch.delenv("ORGTOOL_RUNTIME_DIR", raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    platform_root = tmp_path / "platform-config"
    monkeypatch.setattr(
        "utils.paths.user_config_dir",
        lambda app_name, roaming=True: str(platform_root / app_name),
    )

    paths = RuntimePaths.from_env("DesktopSmartOrganizer")

    assert paths.root == platform_root / "DesktopSmartOrganizer"


def test_config_manager_returns_defaults_when_file_missing(
    tmp_path: Path, monkeypatch
) -> None:
    """Missing config files should load default settings."""
    monkeypatch.setenv("ORGTOOL_RUNTIME_DIR", str(tmp_path))
    manager = ConfigManager.for_app("DesktopSmartOrganizer")

    config = manager.load()

    assert isinstance(config, AppConfig)
    assert config.general.archive_root_name == "桌面整理"
    assert config.invoice.pending_dir_name == "发票归档_待处理"


def test_config_manager_saves_and_reloads_changes(tmp_path: Path, monkeypatch) -> None:
    """Saved configuration should round-trip through JSON."""
    monkeypatch.setenv("ORGTOOL_RUNTIME_DIR", str(tmp_path))
    manager = ConfigManager.for_app("DesktopSmartOrganizer")

    config = manager.load()
    config.general.archive_root_name = "我的桌面归档"
    config.general.desktop_path = "D:/桌面"
    config.invoice.hash_algorithm = "md5"

    manager.save(config)
    reloaded = manager.load()

    assert reloaded.general.archive_root_name == "我的桌面归档"
    assert reloaded.general.desktop_path == "D:/桌面"
    assert reloaded.invoice.hash_algorithm == "md5"

    saved_data = json.loads(manager.paths.config_file.read_text(encoding="utf-8"))
    assert saved_data["general"]["archive_root_name"] == "我的桌面归档"
    assert saved_data["general"]["desktop_path"] == "D:/桌面"
    assert saved_data["invoice"]["hash_algorithm"] == "md5"


def test_config_manager_tolerates_unknown_keys_and_missing_sections(
    tmp_path: Path, monkeypatch
) -> None:
    """Legacy JSON files with unknown keys should still load."""
    monkeypatch.setenv("ORGTOOL_RUNTIME_DIR", str(tmp_path))
    manager = ConfigManager.for_app("DesktopSmartOrganizer")
    manager.paths.root.mkdir(parents=True, exist_ok=True)
    manager.paths.config_file.write_text(
        json.dumps(
            {
                "general": {"archive_root_name": "旧归档", "removed_flag": True},
                "obsolete_section": {"anything": 1},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    config = manager.load()

    assert config.general.archive_root_name == "旧归档"
    assert config.invoice.pending_dir_name == "发票归档_待处理"


def test_runtime_paths_fall_back_when_primary_root_is_not_writable(
    tmp_path: Path, monkeypatch
) -> None:
    """Runtime paths should fall back to the workspace runtime root if the primary root is not writable."""
    blocked_root = tmp_path / "blocked-runtime"
    monkeypatch.setenv("ORGTOOL_RUNTIME_DIR", str(blocked_root))
    monkeypatch.chdir(tmp_path)

    original_ensure_dirs = RuntimePaths.ensure_dirs

    def fake_ensure_dirs(self: RuntimePaths) -> None:
        if self.root == blocked_root:
            raise PermissionError("blocked")
        original_ensure_dirs(self)

    monkeypatch.setattr(RuntimePaths, "ensure_dirs", fake_ensure_dirs)

    paths = RuntimePaths.from_env("DesktopSmartOrganizer")

    assert paths.root == tmp_path / ".runtime" / "DesktopSmartOrganizer"
