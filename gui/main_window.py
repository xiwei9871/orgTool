"""Main application window."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow, QMessageBox, QTabWidget, QWidget

from config.manager import ConfigManager
from core.errors import OperationCancelled
from core.undo_manager import UndoManager
from gui.dialogs.backfill_dialog import BackfillDialog
from gui.dialogs.duplicate_dialog import DuplicateDialog
from gui.dialogs.mail_account_dialog import MailAccountDialog
from gui.dialogs.settings_dialog import SettingsDialog
from gui.pages.desktop_page import DesktopPage
from gui.pages.invoice_page import InvoicePage
from gui.widgets.status_bar import AppStatusBar
from gui.workers.task_worker import TaskWorker
from services.desktop_service import DesktopService
from services.invoice_service import InvoiceService
from services.mail_service import MailService
from utils.desktop import resolve_desktop_directory
from utils.shell import open_in_file_explorer


class MainWindow(QMainWindow):
    """Top-level application window with desktop and invoice pages."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("桌面智能整理工具")
        self.resize(1280, 800)
        self.config_manager = ConfigManager.for_app()
        self.config = self.config_manager.load()
        configured_desktop = self.config.general.desktop_path.strip()
        self.desktop_root = (
            Path(configured_desktop) if configured_desktop else resolve_desktop_directory()
        )
        if not self.config.invoice.root_dir:
            self.config.invoice.root_dir = str(self.desktop_root / "发票管理")
        self.desktop_service = DesktopService(self.config_manager.paths)
        self.invoice_service = InvoiceService(self.config_manager.paths)
        self.mail_service = MailService(
            self.config_manager.paths,
            config_getter=lambda: self.config,
            config_saver=lambda config: self.config_manager.save(config),
        )
        self.undo_manager = UndoManager(self.desktop_service.task_store)
        self.desktop_scan_result: list | None = None
        self.desktop_preview_result: list | None = None
        self.invoice_scan_result: list | None = None
        self.invoice_preview_result: list | None = None

        self._thread_pool = QThreadPool.globalInstance()
        self._cancel_events: set[threading.Event] = set()
        self._workers: set[TaskWorker] = set()
        self._closing = False

        self.page_tabs = QTabWidget()
        self.desktop_page = DesktopPage()
        self.invoice_page = InvoicePage()
        self.page_tabs.addTab(self.desktop_page, "桌面整理")
        self.page_tabs.addTab(self.invoice_page, "发票管理")
        self.setCentralWidget(self.page_tabs)

        self.app_status_bar = AppStatusBar()
        self.setStatusBar(self.app_status_bar)
        self.app_status_bar.cancel_button.clicked.connect(self.cancel_running_tasks)

        self.settings_dialog = SettingsDialog()
        self._bind_events()
        self._refresh_path_labels()
        self._init_mail_sync()

    def _bind_events(self) -> None:
        self.desktop_page.scan_button.clicked.connect(self.scan_desktop)
        self.desktop_page.preview_button.clicked.connect(self.preview_desktop)
        self.desktop_page.execute_button.clicked.connect(self.execute_desktop)
        self.desktop_page.undo_button.clicked.connect(self.undo_desktop)
        self.desktop_page.open_logs_button.clicked.connect(self.open_logs)
        self.desktop_page.settings_button.clicked.connect(self.open_settings)

        self.invoice_page.scan_button.clicked.connect(self.scan_invoices)
        self.invoice_page.preview_button.clicked.connect(self.preview_invoices)
        self.invoice_page.execute_button.clicked.connect(self.execute_invoices)
        self.invoice_page.duplicate_button.clicked.connect(self.show_duplicate_items)
        self.invoice_page.open_logs_button.clicked.connect(self.open_logs)
        self.invoice_page.open_report_button.clicked.connect(self.open_invoice_reports)
        self.invoice_page.open_month_button.clicked.connect(self.open_current_invoice_month)
        self.invoice_page.open_root_button.clicked.connect(self.open_invoice_root)

        panel = self.invoice_page.mail_panel
        panel.add_button.clicked.connect(self.add_mail_account)
        panel.edit_button.clicked.connect(self.edit_mail_account)
        panel.remove_button.clicked.connect(self.remove_mail_account)
        panel.test_button.clicked.connect(self.test_mail_connection)
        panel.backfill_button.clicked.connect(self.start_mail_backfill)
        panel.sync_now_button.clicked.connect(self.sync_mail_now)
        panel.retry_button.clicked.connect(self.sync_mail_now)
        panel.pause_button.clicked.connect(self.mail_service.pause)
        panel.resume_button.clicked.connect(self.mail_service.resume)
        panel.cancel_button.clicked.connect(self.mail_service.cancel)
        panel.open_raw_button.clicked.connect(self.open_mail_raw_dir)
        panel.auto_sync_check.toggled.connect(self._auto_sync_toggled)
        panel.interval_spin.valueChanged.connect(self._auto_sync_interval_changed)

    def _refresh_path_labels(self) -> None:
        self.desktop_page.desktop_path.set_value(str(self.desktop_root))
        self.desktop_page.archive_path.set_value(
            str(self.desktop_root / self.config.general.archive_root_name)
        )
        self.invoice_page.invoice_root_path.set_value(self.config.invoice.root_dir)

    # ------------------------------------------------------------------
    # Background task plumbing

    def _page_buttons(self, page: QWidget) -> list:
        if page is self.desktop_page:
            return [
                self.desktop_page.scan_button,
                self.desktop_page.preview_button,
                self.desktop_page.execute_button,
                self.desktop_page.undo_button,
            ]
        return [
            self.invoice_page.scan_button,
            self.invoice_page.preview_button,
            self.invoice_page.execute_button,
            self.invoice_page.duplicate_button,
        ]

    def _start_task(
        self,
        page: QWidget,
        busy_message: str,
        work: Callable[[threading.Event], Any],
        on_success: Callable[[Any], None],
    ) -> threading.Event:
        """Run ``work`` in the thread pool and apply ``on_success`` on the GUI thread."""
        cancel_event = threading.Event()
        self._cancel_events.add(cancel_event)
        for button in self._page_buttons(page):
            button.setEnabled(False)
        self.app_status_bar.set_cancellable(True)
        self.app_status_bar.set_message(busy_message)

        worker = TaskWorker(work, cancel_event)
        # QThreadPool takes C++ ownership only; keep a Python reference so the
        # runnable is not garbage-collected before run() executes.
        self._workers.add(worker)
        # QueuedConnection guarantees the slots run on the GUI thread: the
        # WorkerSignals object lives on the main thread, so emitted results
        # are posted to this event loop instead of executing in the worker.
        worker.signals.finished.connect(
            lambda result: self._finish_task(
                page, cancel_event, worker, on_success, result
            ),
            Qt.QueuedConnection,
        )
        worker.signals.failed.connect(
            lambda exc: self._fail_task(page, cancel_event, worker, exc),
            Qt.QueuedConnection,
        )
        self._thread_pool.start(worker)
        return cancel_event

    def _finish_task(
        self,
        page: QWidget,
        cancel_event: threading.Event,
        worker: TaskWorker,
        on_success: Callable[[Any], None],
        result: Any,
    ) -> None:
        self._release_task(page, cancel_event, worker)
        on_success(result)

    def _fail_task(
        self,
        page: QWidget,
        cancel_event: threading.Event,
        worker: TaskWorker,
        exc: BaseException,
    ) -> None:
        self._release_task(page, cancel_event, worker)
        if isinstance(exc, OperationCancelled):
            self.app_status_bar.set_message("任务已取消")
            return
        if isinstance(exc, OSError):
            message = f"路径不可用: {exc}"
        else:
            message = f"任务失败: {exc}"
        self.app_status_bar.set_message(message)
        QMessageBox.warning(self, "任务失败", message)

    def _release_task(
        self, page: QWidget, cancel_event: threading.Event, worker: TaskWorker
    ) -> None:
        self._cancel_events.discard(cancel_event)
        self._workers.discard(worker)
        if self._closing:
            return
        for button in self._page_buttons(page):
            button.setEnabled(True)
        if not self._cancel_events:
            self.app_status_bar.set_cancellable(False)

    def cancel_running_tasks(self) -> None:
        """Request cancellation for every running background task."""
        for cancel_event in self._cancel_events:
            cancel_event.set()
        self.app_status_bar.set_message("正在取消任务…")

    def closeEvent(self, event: QCloseEvent) -> None:
        """Stop background work before the window is destroyed."""
        self._closing = True
        self._mail_status_timer.stop()
        self._mail_due_timer.stop()
        self.mail_service.shutdown(timeout=3.0)
        for cancel_event in self._cancel_events:
            cancel_event.set()
        if self._cancel_events:
            self._thread_pool.waitForDone(3000)
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Mail synchronization

    def _init_mail_sync(self) -> None:
        panel = self.invoice_page.mail_panel
        mail_config = self.config.mail
        panel.auto_sync_check.setChecked(mail_config.auto_sync_enabled)
        panel.interval_spin.setValue(mail_config.poll_interval_minutes)
        self._refresh_mail_accounts()

        self._mail_status_timer = QTimer(self)
        self._mail_status_timer.setInterval(1000)
        self._mail_status_timer.timeout.connect(self._refresh_mail_status)
        self._mail_status_timer.start()

        self._mail_due_timer = QTimer(self)
        self._mail_due_timer.setInterval(60_000)
        self._mail_due_timer.timeout.connect(
            lambda: self.mail_service.sync_due_accounts()
        )
        self._mail_due_timer.start()

    def _persist_mail_config(self, _mail=None) -> None:
        self.config_manager.save(self.config)

    def _refresh_mail_accounts(self) -> None:
        accounts = self.mail_service.list_accounts()
        fingerprint = tuple(
            (
                a.account_id,
                a.label,
                a.email,
                a.host,
                a.last_sync_at,
                a.last_error,
                a.enabled,
                tuple(a.folders),
            )
            for a in accounts
        )
        # Rebuilding the table clears the row selection — skip it when
        # nothing changed so the 1-second status timer does not disrupt
        # the user's selection.
        if fingerprint != getattr(self, "_mail_accounts_fp", None):
            self._mail_accounts_fp = fingerprint
            self.invoice_page.mail_panel.set_accounts(accounts)

    def _refresh_mail_status(self) -> None:
        accounts = self.mail_service.list_accounts()
        counts: dict[str, int] = {}
        for account in accounts:
            for key, value in self.mail_service.store.count_by_status(
                account.account_id
            ).items():
                counts[key] = counts.get(key, 0) + value
        snapshot = self.mail_service.status()
        self.invoice_page.mail_panel.update_status(snapshot, counts)
        # When a sync finishes with new downloads, refresh the pending
        # invoice scan so downloaded PDFs appear immediately.
        was_running = getattr(self, "_mail_was_running", False)
        if was_running and not snapshot.running and snapshot.downloaded > 0:
            self.scan_invoices()
        self._mail_was_running = snapshot.running
        self._refresh_mail_accounts()

    def _selected_mail_account(self):
        account_id = self.invoice_page.mail_panel.selected_account_id()
        if account_id:
            return self.mail_service.get_account(account_id)
        accounts = self.mail_service.list_accounts()
        if len(accounts) == 1:
            return accounts[0]
        return None

    def _mail_secret(self, account_id: str) -> str:
        try:
            return self.mail_service.credentials.get_secret(account_id) or ""
        except Exception:  # noqa: BLE001
            return ""

    def add_mail_account(self) -> None:
        dialog = MailAccountDialog(
            folder_lister=self.mail_service.list_folders,
            connection_tester=self.mail_service.test_connection,
            parent=self,
        )
        if dialog.exec():
            account = dialog.build_account()
            try:
                self.mail_service.upsert_account(
                    account, secret=dialog.secret(), persist=self._persist_mail_config
                )
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, "保存失败", f"无法保存账户: {exc}")
                return
            self._refresh_mail_accounts()
            self.app_status_bar.set_message("邮箱账户已添加")

    def edit_mail_account(self) -> None:
        account = self._selected_mail_account()
        if account is None:
            QMessageBox.information(self, "提示", "请先在表格中选择一个邮箱账户")
            return
        dialog = MailAccountDialog(
            account=account,
            folder_lister=self.mail_service.list_folders,
            connection_tester=self.mail_service.test_connection,
            existing_secret=self._mail_secret(account.account_id),
            parent=self,
        )
        if dialog.exec():
            updated = dialog.build_account()
            try:
                self.mail_service.upsert_account(
                    updated, secret=dialog.secret(), persist=self._persist_mail_config
                )
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, "保存失败", f"无法保存账户: {exc}")
                return
            self._refresh_mail_accounts()
            self.app_status_bar.set_message("邮箱账户已更新")

    def remove_mail_account(self) -> None:
        account = self._selected_mail_account()
        if account is None:
            QMessageBox.information(self, "提示", "请先选择一个邮箱账户")
            return
        reply = QMessageBox.question(
            self, "删除账户", f"确定删除账户 {account.label or account.email} 及其授权码吗？"
        )
        if reply != QMessageBox.Yes:
            return
        self.mail_service.delete_account(
            account.account_id, persist=self._persist_mail_config
        )
        self._refresh_mail_accounts()
        self.app_status_bar.set_message("邮箱账户已删除")

    def test_mail_connection(self) -> None:
        account = self._selected_mail_account()
        if account is None:
            QMessageBox.information(self, "提示", "请先选择一个邮箱账户")
            return
        secret = self._mail_secret(account.account_id)

        def work(_ev):
            return self.mail_service.test_connection(account, secret)

        def apply(result) -> None:
            if result.ok:
                QMessageBox.information(self, "连接测试", result.message)
            else:
                QMessageBox.warning(
                    self,
                    "连接测试失败",
                    f"[{result.code}] {result.message}\n阶段: {result.stage}",
                )
            self.app_status_bar.set_message("邮箱连接测试完成")

        self._start_task(self.invoice_page, "正在测试邮箱连接…", work, apply)

    def start_mail_backfill(self) -> None:
        account = self._selected_mail_account()
        if account is None:
            QMessageBox.information(self, "提示", "请先选择一个邮箱账户")
            return
        if not self._mail_secret(account.account_id):
            QMessageBox.warning(self, "缺少授权码", "请先在账户设置中填写授权码")
            return
        secret = self._mail_secret(account.account_id)

        def work(_ev):
            try:
                folders = self.mail_service.list_folders(account, secret)
                return [f.name for f in folders if f.selectable]
            except Exception:  # noqa: BLE001 - fall back to configured names
                return account.folders or ["INBOX"]

        def apply(folder_names) -> None:
            self._open_backfill_dialog(account, folder_names)

        self._start_task(self.invoice_page, "正在获取邮件文件夹…", work, apply)

    def _open_backfill_dialog(self, account, folder_names) -> None:
        dialog = BackfillDialog(folder_names or ["INBOX"], parent=self)
        if not dialog.exec():
            return
        folders = dialog.selected_folders()
        since, until = dialog.date_range()
        started = self.mail_service.start_backfill(
            account.account_id, since=since, until=until, folders=folders
        )
        if not started:
            QMessageBox.information(self, "提示", "该账户已有同步任务在执行")
        else:
            self.app_status_bar.set_message("历史补抓已开始")

    def sync_mail_now(self) -> None:
        account = self._selected_mail_account()
        account_id = account.account_id if account else None
        if account is not None and not self._mail_secret(account.account_id):
            QMessageBox.warning(self, "缺少授权码", "请先在账户设置中填写授权码")
            return
        if self.mail_service.start_incremental(account_id):
            self.app_status_bar.set_message("已启动新邮件同步")
        else:
            QMessageBox.information(self, "提示", "同步任务已在执行")

    def open_mail_raw_dir(self) -> None:
        root = Path(self.config.invoice.root_dir)
        raw_dir = root / self.config.mail.raw_dir_name
        raw_dir.mkdir(parents=True, exist_ok=True)
        open_in_file_explorer(raw_dir)

    def _auto_sync_toggled(self, checked: bool) -> None:
        self.mail_service.set_auto_sync(
            checked, self.invoice_page.mail_panel.interval_spin.value(),
            persist=self._persist_mail_config,
        )
        self.app_status_bar.set_message(
            "自动同步已开启（仅应用运行期间）" if checked else "自动同步已关闭"
        )

    def _auto_sync_interval_changed(self, value: int) -> None:
        self.mail_service.set_auto_sync(
            self.invoice_page.mail_panel.auto_sync_check.isChecked(),
            value,
            persist=self._persist_mail_config,
        )

    # ------------------------------------------------------------------
    # Settings and file manager shortcuts

    def open_settings(self) -> None:
        self.settings_dialog.load_from_config(self.config)
        if self.settings_dialog.exec():
            self.config = self.settings_dialog.apply_to_config(self.config)
            self.config_manager.save(self.config)
            configured_desktop = self.config.general.desktop_path.strip()
            self.desktop_root = (
                Path(configured_desktop)
                if configured_desktop
                else resolve_desktop_directory()
            )
            self._refresh_path_labels()
            self.app_status_bar.set_message("设置已保存")

    def open_logs(self) -> None:
        open_in_file_explorer(self.config_manager.paths.logs_dir)

    def open_invoice_reports(self) -> None:
        report_dir = Path(self.config.invoice.root_dir) / self.config.invoice.report_dir_name
        report_dir.mkdir(parents=True, exist_ok=True)
        open_in_file_explorer(report_dir)

    def open_invoice_root(self) -> None:
        root_dir = Path(self.config.invoice.root_dir)
        root_dir.mkdir(parents=True, exist_ok=True)
        open_in_file_explorer(root_dir)

    def open_current_invoice_month(self) -> None:
        month_root = Path(self.config.invoice.root_dir) / self.config.invoice.monthly_dir_name
        month_root.mkdir(parents=True, exist_ok=True)
        for preview in self.invoice_preview_result or []:
            if preview.target_path:
                target_parent = Path(preview.target_path).parent
                target_parent.mkdir(parents=True, exist_ok=True)
                open_in_file_explorer(target_parent)
                return
        open_in_file_explorer(month_root)

    def show_duplicate_items(self) -> None:
        duplicate_rows = [
            preview
            for preview in self.invoice_preview_result or []
            if preview.duplicate_status in {"强重复", "疑似重复"}
        ]
        if not duplicate_rows:
            QMessageBox.information(self, "重复项", "当前预览中没有重复项。")
            return

        content = "\n".join(
            f"{item.file_name} | {item.duplicate_status} | {item.remark}"
            for item in duplicate_rows
        )
        dialog = DuplicateDialog(content)
        dialog.exec()

    # ------------------------------------------------------------------
    # Desktop organization actions

    def scan_desktop(self, on_done: Callable[[], None] | None = None) -> None:
        if not self.desktop_root.exists():
            message = f"桌面路径不存在: {self.desktop_root}"
            QMessageBox.warning(self, "桌面路径不可用", message)
            self.app_status_bar.set_message(message)
            return

        def work(cancel_event: threading.Event):
            return self.desktop_service.scan_desktop(
                self.desktop_root, self.config, cancel_event
            )

        def apply(items) -> None:
            self.desktop_scan_result = items
            skipped = sum(1 for item in items if item.is_skipped)
            actionable = len(items) - skipped
            self.desktop_page.summary_cards.set_counts(
                len(items), actionable, skipped
            )
            self.app_status_bar.set_message("桌面扫描完成")
            if on_done is not None:
                on_done()

        self._start_task(self.desktop_page, "正在扫描桌面…", work, apply)

    def preview_desktop(self, on_done: Callable[[], None] | None = None) -> None:
        if self.desktop_scan_result is None:
            self.scan_desktop(on_done=lambda: self.preview_desktop(on_done))
            return

        scan_result = list(self.desktop_scan_result)

        def work(cancel_event: threading.Event):
            return self.desktop_service.build_preview(
                scan_result, self.desktop_root, self.config, cancel_event
            )

        def apply(items) -> None:
            self.desktop_preview_result = items
            self.desktop_page.table_model.set_items(items)
            skipped = sum(1 for item in items if item.is_skipped)
            actionable = len(items) - skipped
            self.desktop_page.summary_cards.set_counts(
                len(items), actionable, skipped
            )
            self.app_status_bar.set_message("桌面预览已生成")
            if on_done is not None:
                on_done()

        self._start_task(self.desktop_page, "正在生成桌面预览…", work, apply)

    def execute_desktop(self) -> None:
        if self.desktop_preview_result is None:
            self.preview_desktop(on_done=self.execute_desktop)
            return

        preview_items = list(self.desktop_preview_result)

        def work(cancel_event: threading.Event):
            return self.desktop_service.execute_preview(preview_items, cancel_event)

        def apply(task) -> None:
            QMessageBox.information(
                self,
                "执行完成",
                f"桌面整理完成。移动 {task.summary.get('moved', 0)} 项，跳过 {task.summary.get('skipped', 0)} 项。",
            )
            self.desktop_preview_result = None
            self.scan_desktop()

        self._start_task(self.desktop_page, "正在执行桌面整理…", work, apply)

    def undo_desktop(self) -> None:
        def work(cancel_event: threading.Event):
            return self.undo_manager.undo_latest_desktop_task(cancel_event)

        def apply(task) -> None:
            QMessageBox.information(
                self,
                "撤销完成",
                f"撤销结果：恢复 {task.summary.get('restored', 0)} 项，错误 {task.summary.get('errors', 0)} 项。",
            )
            self.app_status_bar.set_message("撤销操作已完成")
            self.scan_desktop()

        self._start_task(self.desktop_page, "正在撤销上一次整理…", work, apply)

    # ------------------------------------------------------------------
    # Invoice actions

    def scan_invoices(self, on_done: Callable[[], None] | None = None) -> None:
        root_text = str(self.config.invoice.root_dir).strip()
        if not root_text or not Path(root_text).is_dir():
            message = f"发票路径不可用: {root_text or '(未配置)'}"
            QMessageBox.warning(self, "发票路径不可用", message)
            self.app_status_bar.set_message("发票路径不可用")
            self.invoice_page.summary_cards.set_counts(0, 0, 0)
            return

        config = self.config.invoice

        def work(cancel_event: threading.Event):
            return self.invoice_service.scan_pending(config, cancel_event)

        def apply(items) -> None:
            self.invoice_scan_result = items
            self.invoice_page.summary_cards.set_counts(
                len(items), len(items), 0
            )
            self.app_status_bar.set_message("发票扫描完成")
            if on_done is not None:
                on_done()

        self._start_task(self.invoice_page, "正在扫描待处理发票…", work, apply)

    def preview_invoices(self, on_done: Callable[[], None] | None = None) -> None:
        if self.invoice_scan_result is None:
            self.scan_invoices(on_done=lambda: self.preview_invoices(on_done))
            return

        scan_result = list(self.invoice_scan_result)
        config = self.config.invoice

        def work(cancel_event: threading.Event):
            return self.invoice_service.build_preview(scan_result, config, cancel_event)

        def apply(items) -> None:
            self.invoice_preview_result = items
            self.invoice_page.table_model.set_items(items)
            skipped = sum(1 for item in items if item.is_skipped)
            actionable = len(items) - skipped
            self.invoice_page.summary_cards.set_counts(
                len(items), actionable, skipped
            )
            self.app_status_bar.set_message("发票预览已生成")
            if on_done is not None:
                on_done()

        self._start_task(self.invoice_page, "正在生成发票预览…", work, apply)

    def execute_invoices(self) -> None:
        if self.invoice_preview_result is None:
            self.preview_invoices(on_done=self.execute_invoices)
            return

        preview_items = list(self.invoice_preview_result)
        config = self.config.invoice

        def work(cancel_event: threading.Event):
            return self.invoice_service.execute_preview(preview_items, config, cancel_event)

        def apply(task) -> None:
            QMessageBox.information(
                self,
                "执行完成",
                f"发票处理完成。移动 {task.summary.get('moved', 0)} 项，跳过 {task.summary.get('skipped', 0)} 项。",
            )
            self.app_status_bar.set_message("发票处理执行完成")
            self.invoice_preview_result = None
            self.scan_invoices()

        self._start_task(self.invoice_page, "正在执行发票归档…", work, apply)
