"""Tests for the desktop organizer service workflow."""

from __future__ import annotations

from pathlib import Path

from config.schema import AppConfig
from services.desktop_service import DesktopService
from utils.paths import RuntimePaths


def test_desktop_service_scans_builds_preview_and_executes(tmp_path: Path) -> None:
    """The desktop service should orchestrate scan, preview, and execution."""
    desktop_root = tmp_path / "Desktop"
    desktop_root.mkdir()
    (desktop_root / "简历_张三.pdf").write_text("demo", encoding="utf-8")

    runtime_root = tmp_path / "runtime"
    paths = RuntimePaths(
        root=runtime_root,
        config_file=runtime_root / "config.json",
        logs_dir=runtime_root / "logs",
        tasks_dir=runtime_root / "tasks",
        invoice_metadata_dir=runtime_root / "invoice_metadata",
    )
    paths.ensure_dirs()

    service = DesktopService(paths)
    config = AppConfig()

    scanned = service.scan_desktop(desktop_root, config)
    preview = service.build_preview(scanned, desktop_root, config)
    task = service.execute_preview(preview)

    assert len(scanned) == 1
    assert len(preview) == 1
    assert preview[0].suggested_category == "简历"
    assert task.status == "success"
    assert (
        desktop_root / config.general.archive_root_name / "简历" / "简历_张三.pdf"
    ).exists()
