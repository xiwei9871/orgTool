"""Execute desktop preview items as file move tasks."""

from __future__ import annotations

import shutil
import threading
from datetime import datetime
from pathlib import Path

from core.conflict_resolver import resolve_conflict_path
from core.errors import raise_if_cancelled
from core.task_store import TaskStore
from models.desktop import PreviewItem
from models.task import TaskItemRecord, TaskRecord


class MoveExecutor:
    """Move previewed items and persist the resulting task record."""

    def __init__(self, task_store: TaskStore) -> None:
        self.task_store = task_store

    def execute(
        self,
        task_type: str,
        preview_items: list[PreviewItem],
        cancel_event: threading.Event | None = None,
    ) -> TaskRecord:
        """Execute preview items and persist task history."""
        created_at = datetime.now().isoformat(timespec="seconds")
        task_id = f"{task_type}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        task_items: list[TaskItemRecord] = []
        moved_count = 0
        skipped_count = 0
        error_count = 0

        for preview in preview_items:
            raise_if_cancelled(cancel_event)
            if preview.is_skipped:
                skipped_count += 1
                task_items.append(
                    TaskItemRecord(
                        source_path=preview.source_path,
                        target_path=preview.target_path,
                        operation="skip",
                        item_type=preview.file_type,
                        status="skipped",
                        error=preview.skip_reason,
                        extra={"category": preview.suggested_category},
                    )
                )
                continue

            source = Path(preview.source_path)
            target = resolve_conflict_path(Path(preview.target_path))
            target.parent.mkdir(parents=True, exist_ok=True)

            try:
                shutil.move(str(source), str(target))
                moved_count += 1
                task_items.append(
                    TaskItemRecord(
                        source_path=preview.source_path,
                        target_path=str(target),
                        operation="move",
                        item_type=preview.file_type,
                        status="success",
                        error="",
                        extra={"category": preview.suggested_category},
                    )
                )
            except OSError as exc:
                error_count += 1
                task_items.append(
                    TaskItemRecord(
                        source_path=preview.source_path,
                        target_path=str(target),
                        operation="move",
                        item_type=preview.file_type,
                        status="error",
                        error=str(exc),
                        extra={"category": preview.suggested_category},
                    )
                )

        task = TaskRecord(
            task_id=task_id,
            task_type=task_type,
            created_at=created_at,
            status="success" if error_count == 0 else "partial_success",
            items=task_items,
            summary={
                "moved": moved_count,
                "skipped": skipped_count,
                "errors": error_count,
            },
        )
        self.task_store.save(task)
        return task
