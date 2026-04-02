"""Tests for desktop move execution."""

from __future__ import annotations

import json
from pathlib import Path

from core.move_executor import MoveExecutor
from core.task_store import TaskStore
from models.desktop import PreviewItem
from utils.paths import RuntimePaths


def test_move_executor_moves_files_and_records_task(tmp_path: Path) -> None:
    """Executing preview items should move files and persist a task record."""
    source_file = tmp_path / "desktop" / "resume.pdf"
    source_file.parent.mkdir()
    source_file.write_text("demo", encoding="utf-8")
    target_file = tmp_path / "desktop" / "桌面整理" / "简历" / "resume.pdf"
    runtime_root = tmp_path / "runtime"
    paths = RuntimePaths(
        root=runtime_root,
        config_file=runtime_root / "config.json",
        logs_dir=runtime_root / "logs",
        tasks_dir=runtime_root / "tasks",
        invoice_metadata_dir=runtime_root / "invoice_metadata",
    )
    store = TaskStore(paths)

    preview = PreviewItem(
        name="resume.pdf",
        source_path=str(source_file),
        file_type="file",
        suggested_category="简历",
        target_path=str(target_file),
        confidence=0.92,
        reason="keyword: resume keyword",
        is_skipped=False,
        skip_reason="",
        subcategory="",
    )

    task = MoveExecutor(store).execute("desktop_organize", [preview])

    assert task.status == "success"
    assert source_file.exists() is False
    assert target_file.exists() is True

    record_files = list(paths.tasks_dir.glob("*.json"))
    assert len(record_files) == 1
    saved = json.loads(record_files[0].read_text(encoding="utf-8"))
    assert saved["task_type"] == "desktop_organize"
    assert saved["items"][0]["source_path"] == str(source_file)
    assert saved["items"][0]["target_path"] == str(target_file)
