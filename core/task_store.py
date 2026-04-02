"""Persistence for task records."""

from __future__ import annotations

import json
from pathlib import Path

from models.task import TaskRecord
from utils.paths import RuntimePaths


class TaskStore:
    """Save and query task records stored as JSON files."""

    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths
        self.paths.ensure_dirs()

    def save(self, task: TaskRecord) -> Path:
        """Persist a task record and return the written file path."""
        safe_task_id = task.task_id.replace("/", "_").replace("\\", "_")
        safe_created_at = (
            task.created_at.replace(":", "-").replace("/", "-").replace("\\", "-")
        )
        file_path = self.paths.tasks_dir / f"{safe_created_at}_{safe_task_id}.json"
        file_path.write_text(
            json.dumps(task.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return file_path

    def get_latest(self, task_type: str) -> TaskRecord | None:
        """Return the most recent task record for the given task type."""
        latest_record: TaskRecord | None = None

        for path in sorted(self.paths.tasks_dir.glob("*.json")):
            record = TaskRecord.from_dict(
                json.loads(path.read_text(encoding="utf-8"))
            )
            if record.task_type != task_type:
                continue
            if latest_record is None or record.created_at > latest_record.created_at:
                latest_record = record

        return latest_record
