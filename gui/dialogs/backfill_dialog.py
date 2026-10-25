"""Dialog for configuring a historical backfill run."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QRadioButton,
    QVBoxLayout,
)


class BackfillDialog(QDialog):
    """Choose folders + date range (or all visible history) for a backfill."""

    def __init__(self, folder_names: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("历史邮件补抓")
        self.setMinimumWidth(480)

        self.folders_list = QListWidget()
        self.folders_list.setSelectionMode(QListWidget.NoSelection)
        self.folders_list.setMaximumHeight(160)
        for name in folder_names or ["INBOX"]:
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.folders_list.addItem(item)

        self.all_history_radio = QRadioButton("扫描服务器当前可见的全部历史邮件")
        self.all_history_radio.setChecked(True)
        self.range_radio = QRadioButton("按日期范围扫描")
        self.range_radio.toggled.connect(self._toggle_range)

        self.since_edit = QDateEdit(QDate.currentDate().addYears(-1))
        self.since_edit.setCalendarPopup(True)
        self.until_edit = QDateEdit(QDate.currentDate())
        self.until_edit.setCalendarPopup(True)
        self.since_edit.setEnabled(False)
        self.until_edit.setEnabled(False)

        hint = QLabel(
            "提示：部分网易邮箱的客户端收取范围可能限制可见历史邮件数量；"
            "实际可见范围以服务器返回为准。"
        )
        hint.setWordWrap(True)

        form = QFormLayout()
        form.addRow("开始日期", self.since_edit)
        form.addRow("结束日期", self.until_edit)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("选择要扫描的文件夹:"))
        layout.addWidget(self.folders_list)
        layout.addWidget(self.all_history_radio)
        layout.addWidget(self.range_radio)
        range_row = QHBoxLayout()
        range_row.addLayout(form)
        range_row.addStretch(1)
        layout.addLayout(range_row)
        layout.addWidget(hint)
        layout.addWidget(self.button_box)

    def _toggle_range(self, checked: bool) -> None:
        self.since_edit.setEnabled(checked)
        self.until_edit.setEnabled(checked)

    def selected_folders(self) -> list[str]:
        result: list[str] = []
        for row in range(self.folders_list.count()):
            item = self.folders_list.item(row)
            if item.checkState() == Qt.Checked:
                result.append(item.data(Qt.UserRole))
        return result

    def date_range(self) -> tuple[date | None, date | None]:
        """Return (since, until); both None when scanning all history."""
        if self.all_history_radio.isChecked():
            return None, None
        return (
            self.since_edit.date().toPython(),
            self.until_edit.date().toPython(),
        )

    def _on_accept(self) -> None:
        if not self.selected_folders():
            QMessageBox.warning(self, "无法开始", "请至少选择一个文件夹")
            return
        since, until = self.date_range()
        if since is not None and until is not None and since > until:
            QMessageBox.warning(self, "无法开始", "开始日期不能晚于结束日期")
            return
        self.accept()
