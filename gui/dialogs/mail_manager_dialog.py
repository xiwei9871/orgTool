"""Mail account management dialog hosting the full sync panel (S3.3)."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout

from gui.pages.mail_panel import MailSyncPanel


class MailManagerDialog(QDialog):
    """Full mail accounts table and sync controls, moved off the page."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("邮箱账户管理")
        self.resize(900, 480)
        self.panel = MailSyncPanel()
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.panel)
        layout.addWidget(buttons)
