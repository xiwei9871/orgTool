"""Dialog for adding and editing a mail account."""

from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from gui.workers.task_worker import TaskWorker
from mail.models import (
    NETEASE_126,
    NETEASE_163,
    NETEASE_ENTERPRISE,
    SERVER_PRESETS,
    ConnectionProbeResult,
    MailAccountConfig,
    MailFolder,
    guess_preset_for_email,
)


class MailAccountDialog(QDialog):
    """Add/edit one IMAP account with preset server and auth-code entry."""

    def __init__(
        self,
        account: MailAccountConfig | None = None,
        folder_lister: Callable[[MailAccountConfig, str], list[MailFolder]] | None = None,
        connection_tester: Callable[[MailAccountConfig, str], ConnectionProbeResult] | None = None,
        existing_secret: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("邮箱账户")
        self.setMinimumWidth(560)
        self._account_id = account.account_id if account else ""
        self._existing_secret = existing_secret
        self._folder_lister = folder_lister
        self._connection_tester = connection_tester
        self._busy = False

        form = QFormLayout()
        self.label_input = QLineEdit()
        self.label_input.setPlaceholderText("例如：我的163邮箱")
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("name@163.com")
        self.email_input.editingFinished.connect(self._apply_guessed_preset)
        self.preset_combo = QComboBox()
        for preset_id, preset in SERVER_PRESETS.items():
            self.preset_combo.addItem(str(preset["label"]), preset_id)
        self.preset_combo.currentIndexChanged.connect(self._apply_preset)
        self.host_input = QLineEdit()
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(993)
        self.ssl_check = QCheckBox("使用 SSL/TLS（推荐保持开启）")
        self.ssl_check.setChecked(True)
        self.secret_input = QLineEdit()
        self.secret_input.setEchoMode(QLineEdit.Password)
        self.secret_input.setPlaceholderText("客户端授权码（不是邮箱登录密码）")
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 1440)
        self.interval_spin.setValue(15)
        self.interval_spin.setSuffix(" 分钟")
        self.import_check = QCheckBox("下载 PDF 后自动复制到发票待处理目录")
        self.import_check.setChecked(True)

        form.addRow("账户名称", self.label_input)
        form.addRow("邮箱地址", self.email_input)
        form.addRow("服务器预设", self.preset_combo)
        form.addRow("IMAP 服务器", self.host_input)
        form.addRow("端口", self.port_spin)
        form.addRow("加密", self.ssl_check)
        form.addRow("授权码", self.secret_input)
        form.addRow("同步间隔", self.interval_spin)
        form.addRow("发票导入", self.import_check)

        folders_row = QHBoxLayout()
        self.folders_list = QListWidget()
        self.folders_list.setSelectionMode(QListWidget.NoSelection)
        self.folders_list.setMaximumHeight(140)
        folders_row.addWidget(self.folders_list, 1)
        folders_buttons = QVBoxLayout()
        self.fetch_folders_button = QPushButton("获取文件夹列表")
        self.fetch_folders_button.clicked.connect(self.fetch_folders)
        folders_buttons.addWidget(self.fetch_folders_button)
        folders_buttons.addStretch(1)
        folders_row.addLayout(folders_buttons)
        form.addRow("同步文件夹", folders_row)

        action_row = QHBoxLayout()
        self.test_button = QPushButton("测试连接")
        self.test_button.clicked.connect(self.test_connection)
        action_row.addWidget(self.test_button)
        self.result_label = QLabel("")
        action_row.addWidget(self.result_label, 1)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(action_row)
        layout.addWidget(self.button_box)

        if account is not None:
            self.load_account(account)
        else:
            self._apply_preset()

    # ------------------------------------------------------------------
    # Account <-> form

    def load_account(self, account: MailAccountConfig) -> None:
        self._account_id = account.account_id
        self.label_input.setText(account.label)
        self.email_input.setText(account.email)
        index = self.preset_combo.findData(account.preset)
        if index >= 0:
            self.preset_combo.setCurrentIndex(index)
        self.host_input.setText(account.host)
        self.port_spin.setValue(account.port)
        self.ssl_check.setChecked(account.use_ssl)
        self.interval_spin.setValue(account.sync_interval_minutes or 15)
        self.import_check.setChecked(account.import_to_pending)
        if account.folders:
            self.set_folder_names(account.folders, selected=account.folders)

    def build_account(self) -> MailAccountConfig:
        """Build the account config from the form."""
        account = MailAccountConfig(account_id=self._account_id)
        account.label = self.label_input.text().strip()
        account.email = self.email_input.text().strip()
        account.preset = self.preset_combo.currentData()
        account.host = self.host_input.text().strip()
        account.port = self.port_spin.value()
        account.use_ssl = self.ssl_check.isChecked()
        account.sync_interval_minutes = self.interval_spin.value()
        account.import_to_pending = self.import_check.isChecked()
        account.folders = self.selected_folders()
        return account

    def secret(self) -> str:
        """Return the entered auth code, or the preserved existing one."""
        entered = self.secret_input.text().strip()
        return entered or self._existing_secret

    def selected_folders(self) -> list[str]:
        result: list[str] = []
        for row in range(self.folders_list.count()):
            item = self.folders_list.item(row)
            if item.checkState() == Qt.Checked:
                result.append(item.data(Qt.UserRole))
        return result

    def set_folder_names(
        self, names: list[str], selected: list[str] | None = None
    ) -> None:
        self.folders_list.clear()
        selected = selected or ["INBOX"]
        for name in names:
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if name in selected else Qt.Unchecked)
            self.folders_list.addItem(item)

    # ------------------------------------------------------------------
    # Network actions (run on a worker thread)

    def _form_account(self) -> MailAccountConfig:
        return self.build_account()

    def _run_async(self, work, done) -> None:
        if self._busy:
            return
        self._busy = True
        self.test_button.setEnabled(False)
        self.fetch_folders_button.setEnabled(False)
        worker = TaskWorker(work, threading.Event())
        worker.signals.finished.connect(
            lambda result: self._async_done(result, done), Qt.QueuedConnection
        )
        worker.signals.failed.connect(self._async_failed, Qt.QueuedConnection)
        QThreadPool.globalInstance().start(worker)

    def _async_done(self, result, done) -> None:
        self._busy = False
        self.test_button.setEnabled(True)
        self.fetch_folders_button.setEnabled(True)
        done(result)

    def _async_failed(self, exc) -> None:
        self._busy = False
        self.test_button.setEnabled(True)
        self.fetch_folders_button.setEnabled(True)
        self.result_label.setText(f"操作失败: {exc}")

    def fetch_folders(self) -> None:
        """Fetch the selectable folder list from the server."""
        if self._folder_lister is None:
            QMessageBox.information(self, "提示", "文件夹查询不可用")
            return
        account = self._form_account()
        secret = self.secret()
        if not account.email or not secret:
            QMessageBox.warning(self, "提示", "请先填写邮箱地址和授权码")
            return
        self.result_label.setText("正在获取文件夹…")
        self._run_async(
            lambda _ev: self._folder_lister(account, secret),
            self._apply_folders,
        )

    def _apply_folders(self, folders: list[MailFolder]) -> None:
        names = [f.name for f in folders if f.selectable]
        if not names:
            self.result_label.setText("服务器未返回可用文件夹")
            return
        existing = set(self.selected_folders())
        self.set_folder_names(names, selected=list(existing) or ["INBOX"])
        self.result_label.setText(f"发现 {len(names)} 个文件夹")

    def test_connection(self) -> None:
        """Run the staged connection probe."""
        if self._connection_tester is None:
            QMessageBox.information(self, "提示", "连接测试不可用")
            return
        account = self._form_account()
        secret = self.secret()
        if not account.email:
            QMessageBox.warning(self, "提示", "请先填写邮箱地址")
            return
        self.result_label.setText("正在测试连接…")
        self._run_async(
            lambda _ev: self._connection_tester(account, secret),
            self._apply_probe,
        )

    def _apply_probe(self, result: ConnectionProbeResult) -> None:
        if result.ok:
            self.result_label.setText(f"✓ {result.message}")
        else:
            self.result_label.setText(
                f"✗ [{result.code}] {result.message}（阶段: {result.stage}）"
            )

    def _apply_guessed_preset(self) -> None:
        email = self.email_input.text().strip()
        if not email:
            return
        preset_id = guess_preset_for_email(email)
        index = self.preset_combo.findData(preset_id)
        if index >= 0 and preset_id != self.preset_combo.currentData():
            self.preset_combo.setCurrentIndex(index)

    def _apply_preset(self) -> None:
        preset = SERVER_PRESETS.get(self.preset_combo.currentData(), {})
        if preset.get("host"):
            self.host_input.setText(str(preset["host"]))
        if preset.get("port"):
            self.port_spin.setValue(int(preset["port"]))
        self.ssl_check.setChecked(bool(preset.get("use_ssl", True)))
        # Default presets only autofill; users can still edit afterwards.

    def _on_accept(self) -> None:
        account = self.build_account()
        if not account.email or "@" not in account.email:
            QMessageBox.warning(self, "无法保存", "请填写正确的邮箱地址")
            return
        if not account.host:
            QMessageBox.warning(self, "无法保存", "请填写 IMAP 服务器")
            return
        if not account.use_ssl:
            reply = QMessageBox.question(
                self,
                "未加密连接",
                "未启用 SSL/TLS 的连接不安全，确定继续吗？",
            )
            if reply != QMessageBox.Yes:
                return
        if not self.secret():
            QMessageBox.warning(
                self, "无法保存", "请填写客户端授权码（不是邮箱登录密码）"
            )
            return
        self.accept()
