"""Task detail viewer dialog."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QTextEdit, QVBoxLayout


class TaskDetailDialog(QDialog):
    """Simple task detail dialog used for logs or task summaries."""

    def __init__(self, content: str = "") -> None:
        super().__init__()
        self.setWindowTitle("任务详情")
        self.viewer = QTextEdit()
        self.viewer.setReadOnly(True)
        self.viewer.setPlainText(content)

        layout = QVBoxLayout(self)
        layout.addWidget(self.viewer)
