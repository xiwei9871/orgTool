"""Tests for undoing the latest desktop organization task."""

from __future__ import annotations

from pathlib import Path

from core.task_store import TaskStore
from core.undo_manager import UndoManager
from models.task import TaskItemRecord, TaskRecord
from utils.paths import RuntimePaths


def test_undo_manager_restores_latest_desktop_task_in_reverse_order(
    tmp_path: Path,
) -> None:
    """Undo should restore moved files from the latest desktop task."""
    desktop_root = tmp_path / "Desktop"
    archive_root = desktop_root / "桌面整理" / "未确定"
    archive_root.mkdir(parents=True)
    restored_root = desktop_root

    target_a = archive_root / "a.txt"
    target_b = archive_root / "b.txt"
    target_a.write_text("a", encoding="utf-8")
    target_b.write_text("b", encoding="utf-8")

    runtime_root = tmp_path / "runtime"
    paths = RuntimePaths(
        root=runtime_root,
        config_file=runtime_root / "config.json",
        logs_dir=runtime_root / "logs",
        tasks_dir=runtime_root / "tasks",
        invoice_metadata_dir=runtime_root / "invoice_metadata",
    )
    store = TaskStore(paths)
    store.save(
        TaskRecord(
            task_id="desktop-001",
            task_type="desktop_organize",
            created_at="2026-03-06T12:00:00",
            status="success",
            items=[
                TaskItemRecord(
                    source_path=str(restored_root / "a.txt"),
                    target_path=str(target_a),
                    operation="move",
                    item_type="file",
                    status="success",
                ),
                TaskItemRecord(
                    source_path=str(restored_root / "b.txt"),
                    target_path=str(target_b),
                    operation="move",
                    item_type="file",
                    status="success",
                ),
            ],
            summary={"moved": 2},
        )
    )

    undo_task = UndoManager(store).undo_latest_desktop_task()

    assert undo_task.status == "success"
    assert (restored_root / "a.txt").exists()
    assert (restored_root / "b.txt").exists()
    assert target_a.exists() is False
    assert target_b.exists() is False


def test_undo_manager_uses_restored_name_on_source_conflict(tmp_path: Path) -> None:
    """Undo should not overwrite an occupied original location."""
    desktop_root = tmp_path / "Desktop"
    archive_root = desktop_root / "桌面整理" / "简历"
    archive_root.mkdir(parents=True)
    source_path = desktop_root / "resume.pdf"
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text("occupied", encoding="utf-8")
    target_path = archive_root / "resume.pdf"
    target_path.write_text("moved", encoding="utf-8")

    runtime_root = tmp_path / "runtime"
    paths = RuntimePaths(
        root=runtime_root,
        config_file=runtime_root / "config.json",
        logs_dir=runtime_root / "logs",
        tasks_dir=runtime_root / "tasks",
        invoice_metadata_dir=runtime_root / "invoice_metadata",
    )
    store = TaskStore(paths)
    store.save(
        TaskRecord(
            task_id="desktop-001",
            task_type="desktop_organize",
            created_at="2026-03-06T12:30:00",
            status="success",
            items=[
                TaskItemRecord(
                    source_path=str(source_path),
                    target_path=str(target_path),
                    operation="move",
                    item_type="file",
                    status="success",
                )
            ],
            summary={"moved": 1},
        )
    )

    undo_task = UndoManager(store).undo_latest_desktop_task()

    assert undo_task.status == "success"
    assert source_path.read_text(encoding="utf-8") == "occupied"
    assert (desktop_root / "resume (restored 1).pdf").exists()
