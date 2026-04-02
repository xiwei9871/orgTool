"""Tests for task record persistence."""

from __future__ import annotations

from pathlib import Path

from core.task_store import TaskStore
from models.task import TaskItemRecord, TaskRecord
from utils.paths import RuntimePaths


def test_task_store_saves_task_record_as_json(tmp_path: Path) -> None:
    """Saving a task should create a JSON record on disk."""
    paths = RuntimePaths(
        root=tmp_path,
        config_file=tmp_path / "config.json",
        logs_dir=tmp_path / "logs",
        tasks_dir=tmp_path / "tasks",
        invoice_metadata_dir=tmp_path / "invoice_metadata",
    )
    paths.ensure_dirs()
    store = TaskStore(paths)
    task = TaskRecord(
        task_id="desktop-001",
        task_type="desktop_organize",
        created_at="2026-03-06T10:30:00",
        status="success",
        items=[
            TaskItemRecord(
                source_path="C:/Users/test/Desktop/a.txt",
                target_path="C:/Users/test/Desktop/桌面整理/未确定/a.txt",
                operation="move",
                item_type="file",
                status="success",
                error="",
                extra={},
            )
        ],
        summary={"moved": 1},
    )

    record_path = store.save(task)

    assert record_path.exists()
    assert record_path.parent == paths.tasks_dir
    assert "desktop-001" in record_path.name


def test_task_store_returns_latest_task_for_type(tmp_path: Path) -> None:
    """The store should return the latest task for a task type."""
    paths = RuntimePaths(
        root=tmp_path,
        config_file=tmp_path / "config.json",
        logs_dir=tmp_path / "logs",
        tasks_dir=tmp_path / "tasks",
        invoice_metadata_dir=tmp_path / "invoice_metadata",
    )
    paths.ensure_dirs()
    store = TaskStore(paths)

    store.save(
        TaskRecord(
            task_id="desktop-001",
            task_type="desktop_organize",
            created_at="2026-03-06T10:00:00",
            status="success",
            items=[],
            summary={},
        )
    )
    store.save(
        TaskRecord(
            task_id="desktop-002",
            task_type="desktop_organize",
            created_at="2026-03-06T11:00:00",
            status="success",
            items=[],
            summary={},
        )
    )
    store.save(
        TaskRecord(
            task_id="invoice-001",
            task_type="invoice_process",
            created_at="2026-03-06T11:05:00",
            status="success",
            items=[],
            summary={},
        )
    )

    latest = store.get_latest("desktop_organize")

    assert latest is not None
    assert latest.task_id == "desktop-002"
    assert latest.task_type == "desktop_organize"
