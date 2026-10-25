"""One-line mail sync status for the invoice page (S3.3)."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from mail.models import SyncStatusSnapshot


class MailStatusBar(QWidget):
    """Compact sync status + sync/manage buttons; full account
    management lives in :class:`MailManagerDialog`."""

    def __init__(self) -> None:
        super().__init__()
        self.status_label = QLabel("邮箱: 未配置账户")
        self.sync_button = QPushButton("同步")
        self.manage_button = QPushButton("管理邮箱…")
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet("color: #666;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress_label)
        layout.addStretch(1)
        layout.addWidget(self.sync_button)
        layout.addWidget(self.manage_button)

    def set_status(
        self,
        account_names: list[str],
        snapshot: SyncStatusSnapshot,
        counts: dict[str, int],
    ) -> None:
        pending_retry = counts.get("failed", 0) + counts.get(
            "server_unavailable", 0
        )
        name = "、".join(account_names) if account_names else "未配置账户"
        self.status_label.setText(
            f"邮箱: {name} · 已下载 {counts.get('done', 0)} · "
            f"待重试 {pending_retry}"
        )
        if snapshot.running:
            if snapshot.total > 0:
                text = (
                    f"同步中 {snapshot.processed}/{snapshot.total} — "
                    f"{snapshot.folder_name or snapshot.account_label}"
                )
            else:
                text = f"同步中 — {snapshot.folder_name or snapshot.account_label}"
            if snapshot.paused:
                text = "已暂停"
            self.progress_label.setText(text)
        else:
            self.progress_label.setText(
                f"错误: {snapshot.last_error}" if snapshot.last_error else ""
            )
