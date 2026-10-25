"""GUI smoke tests for the main window."""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

import gui.main_window as main_window_module
from config.schema import AppConfig
from core.errors import raise_if_cancelled
from gui.main_window import MainWindow
from utils.paths import RuntimePaths

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app() -> QApplication:
    app = QApplication.instance()
    return app if app is not None else QApplication(sys.argv)


def _runtime_paths(tmp_path: Path) -> RuntimePaths:
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure_dirs()
    return paths


def _fake_manager(config: AppConfig, paths: RuntimePaths) -> SimpleNamespace:
    return SimpleNamespace(
        load=lambda: config,
        save=lambda updated: updated,
        paths=paths,
    )


def _install_fake_manager(
    monkeypatch, config: AppConfig, paths: RuntimePaths
) -> None:
    fake_manager = _fake_manager(config, paths)
    monkeypatch.setattr(
        main_window_module.ConfigManager,
        "for_app",
        classmethod(lambda cls: fake_manager),
    )


def _pump_until(predicate, timeout_seconds: float = 10.0) -> None:
    """Process Qt events until the predicate holds or the deadline passes."""
    app = _app()
    deadline = time.monotonic() + timeout_seconds
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Timed out waiting for background task")
        app.processEvents()
        time.sleep(0.01)


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
    window.desktop_page.desktop_path.set_value(str(tmp_path / "missing-desktop"))

    window.scan_desktop()

    assert "不存在" in window.app_status_bar.message_label.text()


def test_main_window_scan_invoices_handles_invalid_root_gracefully(
    tmp_path: Path, monkeypatch
) -> None:
    """Invoice scanning should not raise on invalid configured paths."""
    _app()
    config = AppConfig()
    config.general.desktop_path = str(tmp_path / "desktop")
    # A regular file is never a usable invoice root on any platform.
    blocking_file = tmp_path / "not-a-directory"
    blocking_file.write_text("x", encoding="utf-8")
    config.invoice.root_dir = str(blocking_file)
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


def test_scan_desktop_runs_in_background_and_updates_ui(
    tmp_path: Path, monkeypatch
) -> None:
    """Desktop scanning should run off the GUI thread and update the page."""
    _app()
    desktop = tmp_path / "桌面 目录"
    desktop.mkdir()
    (desktop / "报告 最终版.txt").write_text("x", encoding="utf-8")
    (desktop / "照片 2026-01.png").write_text("x", encoding="utf-8")

    config = AppConfig()
    config.general.desktop_path = str(desktop)
    _install_fake_manager(monkeypatch, config, _runtime_paths(tmp_path))
    monkeypatch.setattr(
        main_window_module, "resolve_desktop_directory", lambda: desktop
    )

    window = MainWindow()
    window.scan_desktop()

    _pump_until(lambda: window.desktop_scan_result is not None)

    names = [item.name for item in window.desktop_scan_result]
    assert "报告 最终版.txt" in names
    assert "照片 2026-01.png" in names
    assert "扫描完成" in window.app_status_bar.message_label.text()
    assert window.desktop_page.scan_button.isEnabled()


def test_scan_invoices_runs_in_background(tmp_path: Path, monkeypatch) -> None:
    """Invoice scanning should run off the GUI thread."""
    _app()
    desktop = tmp_path / "desktop"
    invoice_root = tmp_path / "发票管理"
    pending = invoice_root / "发票归档_待处理"
    pending.mkdir(parents=True)
    (pending / "测试发票.pdf").write_text("fake", encoding="utf-8")

    config = AppConfig()
    config.general.desktop_path = str(desktop)
    config.invoice.root_dir = str(invoice_root)
    _install_fake_manager(monkeypatch, config, _runtime_paths(tmp_path))
    monkeypatch.setattr(
        main_window_module, "resolve_desktop_directory", lambda: desktop
    )

    window = MainWindow()
    window.scan_invoices()

    _pump_until(lambda: window.invoice_scan_result is not None)

    assert [p.name for p in window.invoice_scan_result] == ["测试发票.pdf"]
    assert "扫描完成" in window.app_status_bar.message_label.text()


def test_cancel_running_tasks_marks_status(tmp_path: Path, monkeypatch) -> None:
    """Cancelling a background task should surface a cancelled status."""
    _app()
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    config = AppConfig()
    config.general.desktop_path = str(desktop)
    _install_fake_manager(monkeypatch, config, _runtime_paths(tmp_path))
    monkeypatch.setattr(
        main_window_module, "resolve_desktop_directory", lambda: desktop
    )

    window = MainWindow()
    started = threading.Event()

    def work(cancel_event: threading.Event) -> None:
        started.set()
        cancel_event.wait(10)
        raise_if_cancelled(cancel_event)

    window._start_task(window.desktop_page, "运行中", work, lambda result: None)
    _pump_until(started.is_set)

    assert not window.desktop_page.scan_button.isEnabled()
    window.cancel_running_tasks()
    _pump_until(
        lambda: "已取消" in window.app_status_bar.message_label.text()
    )
    assert window.desktop_page.scan_button.isEnabled()


def test_close_event_stops_and_waits_for_running_task(
    tmp_path: Path, monkeypatch
) -> None:
    """Closing the window should signal and wait for running tasks."""
    _app()
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    config = AppConfig()
    config.general.desktop_path = str(desktop)
    _install_fake_manager(monkeypatch, config, _runtime_paths(tmp_path))
    monkeypatch.setattr(
        main_window_module, "resolve_desktop_directory", lambda: desktop
    )

    window = MainWindow()
    started = threading.Event()
    finished = threading.Event()

    def work(cancel_event: threading.Event) -> None:
        started.set()
        cancel_event.wait(10)
        finished.set()

    window._start_task(window.desktop_page, "运行中", work, lambda result: None)
    _pump_until(started.is_set)

    window.close()

    assert finished.wait(5)


def test_failed_background_task_shows_warning(tmp_path: Path, monkeypatch) -> None:
    """Worker failures should surface in the status bar and a dialog."""
    _app()
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    config = AppConfig()
    config.general.desktop_path = str(desktop)
    _install_fake_manager(monkeypatch, config, _runtime_paths(tmp_path))
    monkeypatch.setattr(
        main_window_module, "resolve_desktop_directory", lambda: desktop
    )
    warnings: list[str] = []
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "warning",
        lambda *args: warnings.append(str(args[-1])),
    )

    window = MainWindow()
    # Hidden windows no longer open modal warnings (stale queued
    # failures must not deadlock); show it so the dialog path is used.
    window.show()

    def work(cancel_event: threading.Event) -> None:
        raise OSError("disk exploded")

    window._start_task(window.desktop_page, "运行中", work, lambda result: None)
    _pump_until(lambda: "任务失败" in window.app_status_bar.message_label.text() or "路径不可用" in window.app_status_bar.message_label.text())

    assert warnings


def test_undo_desktop_runs_in_background(tmp_path: Path, monkeypatch) -> None:
    """Undo should run via the worker pool without blocking the UI."""
    _app()
    desktop = tmp_path / "desktop"
    desktop.mkdir()
    config = AppConfig()
    config.general.desktop_path = str(desktop)
    _install_fake_manager(monkeypatch, config, _runtime_paths(tmp_path))
    monkeypatch.setattr(
        main_window_module, "resolve_desktop_directory", lambda: desktop
    )
    monkeypatch.setattr(
        main_window_module.QMessageBox, "information", lambda *args: None
    )
    monkeypatch.setattr(
        main_window_module.QMessageBox, "warning", lambda *args: None
    )

    window = MainWindow()
    window.undo_desktop()

    # Wait until the whole undo→rescan chain has applied — otherwise the
    # deferred apply() can pop a real QMessageBox after this test's
    # monkeypatches revert and block the next test's event pump.
    _pump_until(
        lambda: "撤销操作已完成" in window.app_status_bar.message_label.text()
        or "扫描完成" in window.app_status_bar.message_label.text()
    )


def test_desktop_scan_uses_editable_path_and_persists(
    tmp_path: Path, monkeypatch
) -> None:
    """Typing a subdirectory into the scan path field must drive the scan."""
    _app()
    config = AppConfig()
    desktop = tmp_path / "desktop"
    subdir = desktop / "发票管理"
    subdir.mkdir(parents=True)
    (subdir / "note.txt").write_text("x", encoding="utf-8")
    runtime_paths = RuntimePaths(
        root=tmp_path / "runtime",
        config_file=tmp_path / "runtime" / "config.json",
        logs_dir=tmp_path / "runtime" / "logs",
        tasks_dir=tmp_path / "runtime" / "tasks",
        invoice_metadata_dir=tmp_path / "runtime" / "invoice_metadata",
    )
    runtime_paths.ensure_dirs()
    saved: list[AppConfig] = []
    fake_manager = SimpleNamespace(
        load=lambda: config,
        save=lambda updated: saved.append(updated) or updated,
        paths=runtime_paths,
    )
    monkeypatch.setattr(
        main_window_module.ConfigManager,
        "for_app",
        classmethod(lambda cls: fake_manager),
    )
    monkeypatch.setattr(
        main_window_module, "resolve_desktop_directory", lambda: desktop
    )

    window = MainWindow()
    window.desktop_page.desktop_path.set_value(str(subdir))

    window.scan_desktop()
    _pump_until(lambda: window.desktop_scan_result is not None)

    assert window.desktop_root == subdir
    assert saved and saved[-1].general.desktop_path == str(subdir)
    names = [Path(item.path).name for item in window.desktop_scan_result]
    assert "note.txt" in names


def test_invoice_dir_stats_and_folder_buttons(
    tmp_path: Path, monkeypatch
) -> None:
    """Invoice page shows per-subdir counts and folder open targets exist."""
    _app()
    config = AppConfig()
    config.general.desktop_path = str(tmp_path / "desktop")
    inv_root = tmp_path / "发票管理"
    for name, n_files in (
        ("发票归档_待处理", 3),
        ("待审核附件", 2),
        ("按月份归档", 5),
        ("导出报表", 0),
        ("邮件原始附件", 7),
    ):
        d = inv_root / name
        d.mkdir(parents=True)
        for i in range(n_files):
            (d / f"f{i}.pdf").write_text("x", encoding="utf-8")
    (inv_root / "导出报表" / "台账.xlsx").write_text("x", encoding="utf-8")
    config.invoice.root_dir = str(inv_root)
    runtime_paths = RuntimePaths(
        root=tmp_path / "runtime",
        config_file=tmp_path / "runtime" / "config.json",
        logs_dir=tmp_path / "runtime" / "logs",
        tasks_dir=tmp_path / "runtime" / "tasks",
        invoice_metadata_dir=tmp_path / "runtime" / "invoice_metadata",
    )
    runtime_paths.ensure_dirs()
    fake_manager = SimpleNamespace(
        load=lambda: config, save=lambda updated: updated, paths=runtime_paths
    )
    monkeypatch.setattr(
        main_window_module.ConfigManager,
        "for_app",
        classmethod(lambda cls: fake_manager),
    )

    opened: list[str] = []
    monkeypatch.setattr(
        main_window_module, "open_in_file_explorer", lambda p: opened.append(str(p))
    )

    window = MainWindow()
    text = window.invoice_page.dir_stats_label.text()
    assert "待处理 3" in text and "待审核 2" in text
    assert "已归档 5" in text and "报表 1" in text and "邮件原始附件 7" in text

    window.invoice_page.open_pending_button.click()
    window.invoice_page.open_review_button.click()
    window.invoice_page.open_archive_button.click()
    assert opened[-3].endswith("发票归档_待处理")
    assert opened[-2].endswith("待审核附件")
    assert opened[-1].endswith("按月份归档")
