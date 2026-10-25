"""Undo support for the latest successful desktop organization task."""

from __future__ import annotations

import shutil
import threading
from datetime import datetime
from pathlib import Path

from core.errors import raise_if_cancelled
from core.task_store import TaskStore
from models.task import TaskItemRecord, TaskRecord


class UndoManager:
    """Restore the latest successful desktop organization task."""

    def __init__(self, task_store: TaskStore) -> None:
        self.task_store = task_store

    def undo_latest_desktop_task(
        self, cancel_event: threading.Event | None = None
    ) -> TaskRecord:
        """Undo the latest successful desktop organization task."""
        latest_task = self.task_store.get_latest("desktop_organize")
        created_at = datetime.now().isoformat(timespec="seconds")
        undo_task = TaskRecord(
            task_id=f"desktop-undo-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            task_type="desktop_undo",
            created_at=created_at,
            status="success",
            items=[],
            summary={},
        )

        if latest_task is None:
            undo_task.status = "error"
            undo_task.summary = {"restored": 0, "errors": 1}
            self.task_store.save(undo_task)
            return undo_task

        restored_count = 0
        error_count = 0

        for item in reversed(latest_task.items):
            raise_if_cancelled(cancel_event)
            if item.operation != "move" or item.status != "success":
                continue

            source = Path(item.source_path)
            target = Path(item.target_path)

            if not target.exists():
                error_count += 1
                undo_task.items.append(
                    TaskItemRecord(
                        source_path=str(target),
                        target_path=str(source),
                        operation="undo_move",
                        item_type=item.item_type,
                        status="error",
                        error="target_missing",
                        extra={"original_task_id": latest_task.task_id},
                    )
                )
                continue

            restore_path = _resolve_restore_path(source)
            restore_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                shutil.move(str(target), str(restore_path))
                restored_count += 1
                undo_task.items.append(
                    TaskItemRecord(
                        source_path=str(target),
                        target_path=str(restore_path),
                        operation="undo_move",
                        item_type=item.item_type,
                        status="success",
                        error="",
                        extra={"original_task_id": latest_task.task_id},
                    )
                )
            except OSError as exc:
                error_count += 1
                undo_task.items.append(
                    TaskItemRecord(
                        source_path=str(target),
                        target_path=str(restore_path),
                        operation="undo_move",
                        item_type=item.item_type,
                        status="error",
                        error=str(exc),
                        extra={"original_task_id": latest_task.task_id},
                    )
                )

        undo_task.status = "success" if error_count == 0 else "partial_success"
        undo_task.summary = {"restored": restored_count, "errors": error_count}
        self.task_store.save(undo_task)
        return undo_task


def _resolve_restore_path(original_path: Path) -> Path:
    """Return a safe restore path that does not overwrite existing files."""
    if not original_path.exists():
        return original_path

    parent = original_path.parent
    stem = original_path.stem
    suffix = original_path.suffix
    index = 1

    while True:
        candidate = parent / f"{stem} (restored {index}){suffix}"
        if not candidate.exists():
            return candidate
        index += 1
