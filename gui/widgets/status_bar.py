"""Status bar helper widget."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QStatusBar


class AppStatusBar(QStatusBar):
    """Status bar with a single shared message label."""

    def __init__(self) -> None:
        super().__init__()
        self.message_label = QLabel("就绪")
        self.addWidget(self.message_label)

    def set_message(self, message: str) -> None:
        self.message_label.setText(message)
