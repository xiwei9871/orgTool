"""Status bar helper widget."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPushButton, QStatusBar


class AppStatusBar(QStatusBar):
    """Status bar with a message label and a task cancel button."""

    def __init__(self) -> None:
        super().__init__()
        self.message_label = QLabel("就绪")
        self.cancel_button = QPushButton("取消任务")
        self.cancel_button.setVisible(False)
        self.addWidget(self.message_label, 1)
        self.addWidget(self.cancel_button)

    def set_message(self, message: str) -> None:
        self.message_label.setText(message)

    def set_cancellable(self, cancellable: bool) -> None:
        """Show or hide the cancel button for running tasks."""
        self.cancel_button.setVisible(cancellable)
