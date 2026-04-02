"""Task record models used for execution logs and undo."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class TaskItemRecord:
    """A single file operation within a task."""

    source_path: str
    target_path: str
    operation: str
    item_type: str
    status: str
    error: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TaskRecord:
    """A persisted task record for preview execution or undo."""

    task_id: str
    task_type: str
    created_at: str
    status: str
    items: list[TaskItemRecord] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert the task record into JSON-serializable data."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskRecord":
        """Hydrate a task record from stored JSON data."""
        return cls(
            task_id=data["task_id"],
            task_type=data["task_type"],
            created_at=data["created_at"],
            status=data["status"],
            items=[TaskItemRecord(**item) for item in data.get("items", [])],
            summary=data.get("summary", {}),
        )
