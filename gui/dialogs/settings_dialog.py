"""Application settings dialog."""

from __future__ import annotations

from config.schema import AppConfig
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
)


class SettingsDialog(QDialog):
    """Minimal settings dialog for MVP configuration access."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("设置")
        form = QFormLayout()
        self.archive_name_input = QLineEdit()
        self.desktop_path_input = QLineEdit()
        self.invoice_root_input = QLineEdit()
        form.addRow("桌面归档目录名", self.archive_name_input)
        form.addRow("桌面路径", self.desktop_path_input)
        form.addRow("发票主目录", self.invoice_root_input)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.button_box)

    def load_from_config(self, config: AppConfig) -> None:
        """Populate the dialog from application config."""
        self.archive_name_input.setText(config.general.archive_root_name)
        self.desktop_path_input.setText(config.general.desktop_path)
        self.invoice_root_input.setText(config.invoice.root_dir)

    def apply_to_config(self, config: AppConfig) -> AppConfig:
        """Write dialog values back to the config object."""
        config.general.archive_root_name = self.archive_name_input.text().strip() or "桌面整理"
        config.general.desktop_path = self.desktop_path_input.text().strip()
        config.invoice.root_dir = self.invoice_root_input.text().strip()
        return config
