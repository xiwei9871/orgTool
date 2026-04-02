"""Simple labeled path display."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget


class PathSelector(QWidget):
    """A compact path display used in page headers."""

    def __init__(self, label: str, value: str = "") -> None:
        super().__init__()
        self.label = QLabel(label)
        self.value_label = QLabel(value)

        layout = QHBoxLayout(self)
        layout.addWidget(self.label)
        layout.addWidget(self.value_label, 1)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)
