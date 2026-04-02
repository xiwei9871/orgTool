"""GUI smoke tests for the main window."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

import gui.main_window as main_window_module
from config.schema import AppConfig
from gui.main_window import MainWindow
from utils.paths import RuntimePaths

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app() -> QApplication:
    app = QApplication.instance()
    return app if app is not None else QApplication(sys.argv)


def test_main_window_instantiates_with_two_pages() -> None:
    """The main window should expose desktop and invoice pages."""
    _app()
    window = MainWindow()

    assert window.windowTitle() == "桌面智能整理工具"
    assert window.page_tabs.count() == 2


def test_main_window_uses_resolved_desktop_path(
    tmp_path: Path, monkeypatch
) -> None:
    """The main window should use the Windows desktop resolver result."""
    _app()
    config = AppConfig()
    runtime_paths = RuntimePaths(
        root=tmp_path / "runtime",
        config_file=tmp_path / "runtime" / "config.json",
        logs_dir=tmp_path / "runtime" / "logs",
        tasks_dir=tmp_path / "runtime" / "tasks",
        invoice_metadata_dir=tmp_path / "runtime" / "invoice_metadata",
    )
    runtime_paths.ensure_dirs()
    fake_manager = SimpleNamespace(
        load=lambda: config,
        save=lambda updated: updated,
        paths=runtime_paths,
    )
    monkeypatch.setattr(
        main_window_module.ConfigManager,
        "for_app",
        classmethod(lambda cls: fake_manager),
    )
    monkeypatch.setattr(
        main_window_module,
        "resolve_desktop_directory",
        lambda: tmp_path,
    )

    window = MainWindow()

    assert window.desktop_root == tmp_path


def test_main_window_scan_desktop_handles_missing_path_gracefully(
    tmp_path: Path, monkeypatch
) -> None:
    """Scanning should not raise when the desktop path does not exist."""
    _app()
    monkeypatch.setattr(
        main_window_module,
        "resolve_desktop_directory",
        lambda: tmp_path,
    )
    monkeypatch.setattr(main_window_module.QMessageBox, "warning", lambda *args: None)

    window = MainWindow()
    window.desktop_root = tmp_path / "missing-desktop"

    window.scan_desktop()

    assert "不存在" in window.app_status_bar.message_label.text()


def test_main_window_scan_invoices_handles_invalid_root_gracefully(
    tmp_path: Path, monkeypatch
) -> None:
    """Invoice scanning should not raise on invalid configured paths."""
    _app()
    config = AppConfig()
    config.general.desktop_path = str(tmp_path / "desktop")
    config.invoice.root_dir = "D:\\??\\????"
    runtime_paths = RuntimePaths(
        root=tmp_path / "runtime",
        config_file=tmp_path / "runtime" / "config.json",
        logs_dir=tmp_path / "runtime" / "logs",
        tasks_dir=tmp_path / "runtime" / "tasks",
        invoice_metadata_dir=tmp_path / "runtime" / "invoice_metadata",
    )
    runtime_paths.ensure_dirs()
    fake_manager = SimpleNamespace(
        load=lambda: config,
        save=lambda updated: updated,
        paths=runtime_paths,
    )

    monkeypatch.setattr(
        main_window_module.ConfigManager,
        "for_app",
        classmethod(lambda cls: fake_manager),
    )
    monkeypatch.setattr(main_window_module.QMessageBox, "warning", lambda *args: None)

    window = MainWindow()

    window.scan_invoices()

    assert "发票路径不可用" in window.app_status_bar.message_label.text()


def test_main_window_prefers_configured_desktop_path(
    tmp_path: Path, monkeypatch
) -> None:
    """Configured desktop paths should override automatic resolution."""
    _app()
    config = AppConfig()
    configured_desktop = tmp_path / "desktop-custom"
    configured_desktop.mkdir()
    config.general.desktop_path = str(configured_desktop)
    runtime_paths = RuntimePaths(
        root=tmp_path / "runtime",
        config_file=tmp_path / "runtime" / "config.json",
        logs_dir=tmp_path / "runtime" / "logs",
        tasks_dir=tmp_path / "runtime" / "tasks",
        invoice_metadata_dir=tmp_path / "runtime" / "invoice_metadata",
    )
    runtime_paths.ensure_dirs()

    fake_manager = SimpleNamespace(
        load=lambda: config,
        save=lambda updated: updated,
        paths=runtime_paths,
    )

    monkeypatch.setattr(
        main_window_module.ConfigManager,
        "for_app",
        classmethod(lambda cls: fake_manager),
    )
    monkeypatch.setattr(
        main_window_module,
        "resolve_desktop_directory",
        lambda: tmp_path / "auto-desktop",
    )

    window = MainWindow()

    assert window.desktop_root == configured_desktop
