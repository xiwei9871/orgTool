"""Main application window."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QMainWindow, QMessageBox, QTabWidget

from config.manager import ConfigManager
from core.undo_manager import UndoManager
from gui.dialogs.duplicate_dialog import DuplicateDialog
from gui.dialogs.settings_dialog import SettingsDialog
from gui.pages.desktop_page import DesktopPage
from gui.pages.invoice_page import InvoicePage
from gui.widgets.status_bar import AppStatusBar
from services.desktop_service import DesktopService
from services.invoice_service import InvoiceService
from utils.shell import open_in_file_explorer
from utils.windows import resolve_desktop_directory


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
        self.undo_manager = UndoManager(self.desktop_service.task_store)
        self.desktop_scan_result = []
        self.desktop_preview_result = []
        self.invoice_scan_result = []
        self.invoice_preview_result = []

        self.page_tabs = QTabWidget()
        self.desktop_page = DesktopPage()
        self.invoice_page = InvoicePage()
        self.page_tabs.addTab(self.desktop_page, "桌面整理")
        self.page_tabs.addTab(self.invoice_page, "发票管理")
        self.setCentralWidget(self.page_tabs)

        self.app_status_bar = AppStatusBar()
        self.setStatusBar(self.app_status_bar)

        self.settings_dialog = SettingsDialog()
        self._bind_events()
        self._refresh_path_labels()

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

    def _refresh_path_labels(self) -> None:
        self.desktop_page.desktop_path.set_value(str(self.desktop_root))
        self.desktop_page.archive_path.set_value(
            str(self.desktop_root / self.config.general.archive_root_name)
        )
        self.invoice_page.invoice_root_path.set_value(self.config.invoice.root_dir)

    def open_settings(self) -> None:
        self.settings_dialog.load_from_config(self.config)
        if self.settings_dialog.exec():
            self.config = self.settings_dialog.apply_to_config(self.config)
            self.config_manager.save(self.config)
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
        for preview in self.invoice_preview_result:
            if preview.target_path:
                target_parent = Path(preview.target_path).parent
                target_parent.mkdir(parents=True, exist_ok=True)
                open_in_file_explorer(target_parent)
                return
        open_in_file_explorer(month_root)

    def show_duplicate_items(self) -> None:
        duplicate_rows = [
            preview
            for preview in self.invoice_preview_result
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

    def scan_desktop(self) -> None:
        if not self.desktop_root.exists():
            message = f"桌面路径不存在: {self.desktop_root}"
            QMessageBox.warning(self, "桌面路径不可用", message)
            self.app_status_bar.set_message(message)
            return

        self.desktop_scan_result = self.desktop_service.scan_desktop(
            self.desktop_root, self.config
        )
        skipped = sum(1 for item in self.desktop_scan_result if item.is_skipped)
        actionable = len(self.desktop_scan_result) - skipped
        self.desktop_page.summary_cards.set_counts(
            len(self.desktop_scan_result), actionable, skipped
        )
        self.app_status_bar.set_message("桌面扫描完成")

    def preview_desktop(self) -> None:
        if not self.desktop_scan_result:
            self.scan_desktop()
        self.desktop_preview_result = self.desktop_service.build_preview(
            self.desktop_scan_result,
            self.desktop_root,
            self.config,
        )
        self.desktop_page.table_model.set_items(self.desktop_preview_result)
        skipped = sum(1 for item in self.desktop_preview_result if item.is_skipped)
        actionable = len(self.desktop_preview_result) - skipped
        self.desktop_page.summary_cards.set_counts(
            len(self.desktop_preview_result), actionable, skipped
        )
        self.app_status_bar.set_message("桌面预览已生成")

    def execute_desktop(self) -> None:
        if not self.desktop_preview_result:
            self.preview_desktop()
        task = self.desktop_service.execute_preview(self.desktop_preview_result)
        QMessageBox.information(
            self,
            "执行完成",
            f"桌面整理完成。移动 {task.summary.get('moved', 0)} 项，跳过 {task.summary.get('skipped', 0)} 项。",
        )
        self.app_status_bar.set_message("桌面整理执行完成")
        self.desktop_preview_result = []
        self.scan_desktop()

    def undo_desktop(self) -> None:
        task = self.undo_manager.undo_latest_desktop_task()
        QMessageBox.information(
            self,
            "撤销完成",
            f"撤销结果：恢复 {task.summary.get('restored', 0)} 项，错误 {task.summary.get('errors', 0)} 项。",
        )
        self.app_status_bar.set_message("撤销操作已完成")
        self.scan_desktop()

    def scan_invoices(self) -> None:
        try:
            self.invoice_scan_result = self.invoice_service.scan_pending(
                self.config.invoice
            )
        except OSError as exc:
            message = f"发票路径不可用: {self.config.invoice.root_dir} ({exc})"
            QMessageBox.warning(self, "发票路径不可用", message)
            self.app_status_bar.set_message("发票路径不可用")
            self.invoice_page.summary_cards.set_counts(0, 0, 0)
            return

        self.invoice_page.summary_cards.set_counts(
            len(self.invoice_scan_result), len(self.invoice_scan_result), 0
        )
        self.app_status_bar.set_message("发票扫描完成")

    def preview_invoices(self) -> None:
        if not self.invoice_scan_result:
            self.scan_invoices()
        self.invoice_preview_result = self.invoice_service.build_preview(
            self.invoice_scan_result, self.config.invoice
        )
        self.invoice_page.table_model.set_items(self.invoice_preview_result)
        skipped = sum(1 for item in self.invoice_preview_result if item.is_skipped)
        actionable = len(self.invoice_preview_result) - skipped
        self.invoice_page.summary_cards.set_counts(
            len(self.invoice_preview_result), actionable, skipped
        )
        self.app_status_bar.set_message("发票预览已生成")

    def execute_invoices(self) -> None:
        if not self.invoice_preview_result:
            self.preview_invoices()
        task = self.invoice_service.execute_preview(
            self.invoice_preview_result, self.config.invoice
        )
        QMessageBox.information(
            self,
            "执行完成",
            f"发票处理完成。移动 {task.summary.get('moved', 0)} 项，跳过 {task.summary.get('skipped', 0)} 项。",
        )
        self.app_status_bar.set_message("发票处理执行完成")
        self.invoice_preview_result = []
        self.scan_invoices()
