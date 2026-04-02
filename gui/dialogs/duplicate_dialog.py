"""Duplicate item viewer dialog."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QTextEdit, QVBoxLayout


class DuplicateDialog(QDialog):
    """Show duplicate invoice details."""

    def __init__(self, content: str = "") -> None:
        super().__init__()
        self.setWindowTitle("重复项")
        self.viewer = QTextEdit()
        self.viewer.setReadOnly(True)
        self.viewer.setPlainText(content)

        layout = QVBoxLayout(self)
        layout.addWidget(self.viewer)
