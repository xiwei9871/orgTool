"""Editable path row with a directory picker."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)


class EditablePathRow(QWidget):
    """Label + editable path field + browse button.

    Exposes ``set_value``/``text`` so it can drop in wherever a
    display-only ``PathSelector`` was used before.
    """

    def __init__(self, label: str, value: str = "") -> None:
        super().__init__()
        self.label = QLabel(label)
        self.path_edit = QLineEdit(value)
        self.path_edit.setPlaceholderText("留空则使用默认路径")
        self.browse_button = QPushButton("浏览…")
        self.browse_button.clicked.connect(self._browse)

        layout = QHBoxLayout(self)
        layout.addWidget(self.label)
        layout.addWidget(self.path_edit, 1)
        layout.addWidget(self.browse_button)

    def _browse(self) -> None:
        current = self.path_edit.text().strip()
        start = current if current and Path(current).expanduser().exists() else str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "选择目录", start)
        if chosen:
            self.path_edit.setText(chosen)

    def set_value(self, value: str) -> None:
        self.path_edit.setText(value)

    def text(self) -> str:
        return self.path_edit.text()
