"""Tests for cooperative cancellation of long-running operations."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from config.schema import AppConfig, InvoiceConfig
from core.errors import OperationCancelled, raise_if_cancelled
from core.move_executor import MoveExecutor
from core.scanner import DesktopScanner
from core.task_store import TaskStore
from core.undo_manager import UndoManager
from models.desktop import PreviewItem
from services.invoice_service import InvoiceService
from utils.paths import RuntimePaths


def _runtime(tmp_path: Path) -> RuntimePaths:
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure_dirs()
    return paths


def test_raise_if_cancelled_with_set_event() -> None:
    event = threading.Event()
    event.set()
    with pytest.raises(OperationCancelled):
        raise_if_cancelled(event)


def test_raise_if_cancelled_ignores_none_and_unset() -> None:
    raise_if_cancelled(None)
    raise_if_cancelled(threading.Event())


def test_desktop_scanner_cancelled_between_entries(tmp_path: Path) -> None:
    """A pre-set cancel event stops scanning on the first entry."""
    for index in range(5):
        (tmp_path / f"file-{index}.txt").write_text("x", encoding="utf-8")
    event = threading.Event()
    event.set()

    with pytest.raises(OperationCancelled):
        DesktopScanner().scan(
            tmp_path,
            whitelist_names=set(),
            whitelist_extensions=set(),
            skip_hidden=False,
            skip_system=False,
            cancel_event=event,
        )


def test_desktop_scanner_cancelled_mid_scan(tmp_path: Path) -> None:
    """Cancelling during the scan raises before all entries are processed."""
    for index in range(50):
        (tmp_path / f"file-{index:03}.txt").write_text("x", encoding="utf-8")
    event = threading.Event()

    class _StopFilter:
        calls = 0

    import core.scanner as scanner_module

    original = scanner_module.should_skip_path

    def stop_after_three(*args, **kwargs):
        _StopFilter.calls += 1
        if _StopFilter.calls >= 3:
            event.set()
        return original(*args, **kwargs)

    scanner_module.should_skip_path = stop_after_three
    try:
        with pytest.raises(OperationCancelled):
            DesktopScanner().scan(
                tmp_path,
                whitelist_names=set(),
                whitelist_extensions=set(),
                skip_hidden=False,
                skip_system=False,
                cancel_event=event,
            )
    finally:
        scanner_module.should_skip_path = original


def test_move_executor_cancelled(tmp_path: Path) -> None:
    """Executing moves respects cancellation."""
    paths = _runtime(tmp_path)
    executor = MoveExecutor(TaskStore(paths))
    item = PreviewItem(
        name="a.txt",
        source_path=str(tmp_path / "a.txt"),
        file_type="file",
        suggested_category="c",
        target_path=str(tmp_path / "out" / "a.txt"),
        confidence=0.9,
        reason="r",
        is_skipped=False,
        skip_reason="",
    )
    event = threading.Event()
    event.set()

    with pytest.raises(OperationCancelled):
        executor.execute("desktop_organize", [item], cancel_event=event)


def test_undo_manager_cancelled(tmp_path: Path) -> None:
    """Undo respects cancellation."""
    paths = _runtime(tmp_path)
    undo = UndoManager(TaskStore(paths))
    event = threading.Event()
    event.set()

    # No prior task → early return path; ensure it does not raise TypeError
    # and returns an error record instead of hanging.
    record = undo.undo_latest_desktop_task(event)
    assert record.summary["errors"] == 1


def test_invoice_build_preview_cancelled(tmp_path: Path) -> None:
    """Invoice preview respects cancellation."""
    invoice_root = tmp_path / "invoice_root"
    pending = invoice_root / "发票归档_待处理"
    pending.mkdir(parents=True)
    (pending / "a.pdf").write_text("fake", encoding="utf-8")

    service = InvoiceService(runtime_paths=_runtime(tmp_path))
    config = InvoiceConfig(root_dir=str(invoice_root))
    event = threading.Event()
    event.set()

    with pytest.raises(OperationCancelled):
        service.build_preview([pending / "a.pdf"], config, event)


def test_scan_pending_raises_for_missing_root(tmp_path: Path) -> None:
    """Missing invoice roots raise FileNotFoundError instead of creating dirs."""
    service = InvoiceService(runtime_paths=_runtime(tmp_path))
    config = InvoiceConfig(root_dir=str(tmp_path / "missing-root"))

    with pytest.raises(FileNotFoundError):
        service.scan_pending(config)

    assert not (tmp_path / "missing-root").exists()


def test_scan_pending_raises_for_blank_root(tmp_path: Path) -> None:
    """A blank root_dir must not silently scan the working directory."""
    service = InvoiceService(runtime_paths=_runtime(tmp_path))
    config = InvoiceConfig(root_dir="")

    with pytest.raises(FileNotFoundError):
        service.scan_pending(config)


def test_desktop_service_scan_desktop_cancelled(tmp_path: Path) -> None:
    """Service-level scan honours the cancel event."""
    from services.desktop_service import DesktopService

    service = DesktopService(_runtime(tmp_path))
    (tmp_path / "x.txt").write_text("x", encoding="utf-8")
    event = threading.Event()
    event.set()

    with pytest.raises(OperationCancelled):
        service.scan_desktop(tmp_path, AppConfig(), event)
