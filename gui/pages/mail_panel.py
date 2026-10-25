"""Mail synchronization panel embedded in the invoice page."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from mail.importer import mask_email
from mail.models import MailAccountConfig, SyncStatusSnapshot

ACCOUNT_COL_ID = Qt.UserRole


class MailSyncPanel(QGroupBox):
    """Accounts table + live sync stats + control buttons."""

    def __init__(self) -> None:
        super().__init__("邮箱同步")

        self.accounts_table = QTableWidget(0, 5)
        self.accounts_table.setHorizontalHeaderLabels(
            ["账户", "服务器", "文件夹", "上次同步", "状态/错误"]
        )
        self.accounts_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self.accounts_table.verticalHeader().setVisible(False)
        self.accounts_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.accounts_table.setSelectionMode(QTableWidget.SingleSelection)
        self.accounts_table.setMaximumHeight(150)

        self.add_button = QPushButton("添加邮箱")
        self.edit_button = QPushButton("修改")
        self.remove_button = QPushButton("删除")
        self.test_button = QPushButton("测试连接")
        self.backfill_button = QPushButton("历史补抓")
        self.sync_now_button = QPushButton("立即同步")
        self.pause_button = QPushButton("暂停")
        self.resume_button = QPushButton("恢复")
        self.cancel_button = QPushButton("取消")
        self.open_raw_button = QPushButton("打开附件目录")

        button_row = QHBoxLayout()
        for button in (
            self.add_button,
            self.edit_button,
            self.remove_button,
            self.test_button,
            self.backfill_button,
            self.sync_now_button,
            self.pause_button,
            self.resume_button,
            self.cancel_button,
            self.open_raw_button,
        ):
            button_row.addWidget(button)
        button_row.addStretch(1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("空闲")

        self.stats_label = QLabel(
            "扫描: 0 | 发现附件: 0 | 已下载: 0 | 重复跳过: 0 | 失败: 0"
        )
        self.last_error_label = QLabel("")

        self.auto_sync_check = QCheckBox("应用运行期间自动同步")
        self.auto_sync_check.setChecked(True)
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 1440)
        self.interval_spin.setValue(15)
        self.interval_spin.setSuffix(" 分钟")
        auto_note = QLabel("自动同步仅在应用运行期间执行，退出应用后不再同步。")

        auto_row = QHBoxLayout()
        auto_row.addWidget(self.auto_sync_check)
        auto_row.addWidget(QLabel("轮询间隔"))
        auto_row.addWidget(self.interval_spin)
        auto_row.addWidget(auto_note)
        auto_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.accounts_table)
        layout.addLayout(button_row)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.stats_label)
        layout.addWidget(self.last_error_label)
        layout.addLayout(auto_row)

    # ------------------------------------------------------------------
    # View updates

    def set_accounts(self, accounts: list[MailAccountConfig]) -> None:
        self.accounts_table.setRowCount(len(accounts))
        for row, account in enumerate(accounts):
            name = account.label or mask_email(account.email)
            values = [
                name,
                f"{account.host}:{account.port}",
                ", ".join(account.folders) if account.folders else "INBOX",
                account.last_sync_at or "从未",
                account.last_error or ("就绪" if account.enabled else "已停用"),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setData(ACCOUNT_COL_ID, account.account_id)
                self.accounts_table.setItem(row, col, item)

    def selected_account_id(self) -> str | None:
        row = self.accounts_table.currentRow()
        if row < 0:
            return None
        item = self.accounts_table.item(row, 0)
        return item.data(ACCOUNT_COL_ID) if item else None

    def update_status(self, snapshot: SyncStatusSnapshot, counts: dict[str, int]) -> None:
        scanned = snapshot.processed
        found = counts.get("done", 0) + counts.get("skipped_duplicate", 0) + counts.get("failed", 0) + counts.get("pending", 0) + counts.get("downloading", 0)
        downloaded = snapshot.downloaded
        self.stats_label.setText(
            f"扫描: {scanned} | 发现附件: {found} | 已下载: {downloaded} | "
            f"重复跳过: {snapshot.skipped_duplicate} | 失败: {snapshot.failed}"
        )
        if snapshot.running:
            if snapshot.total > 0:
                self.progress_bar.setRange(0, snapshot.total)
                self.progress_bar.setValue(min(snapshot.processed, snapshot.total))
                self.progress_bar.setFormat(
                    f"%v/%m — {snapshot.folder_name or snapshot.account_label}"
                )
            else:
                self.progress_bar.setRange(0, 0)
                self.progress_bar.setFormat(
                    f"运行中 — {snapshot.folder_name or snapshot.account_label}"
                )
            if snapshot.paused:
                self.progress_bar.setFormat("已暂停")
        else:
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setFormat("空闲")
        if snapshot.last_error:
            self.last_error_label.setText(
                f"上次错误: [{snapshot.last_error_code}] {snapshot.last_error}"
            )
