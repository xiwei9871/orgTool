"""Invoice management page."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from gui.dialogs.mail_manager_dialog import MailManagerDialog
from gui.models.invoice_table_model import InvoiceTableModel
from gui.widgets.mail_status_bar import MailStatusBar
from gui.widgets.path_selector import PathSelector
from gui.widgets.summary_cards import SummaryCards


class InvoicePage(QWidget):
    """Invoice processing controls and preview table.

    Layout order (top to bottom): invoice root path, one-line mail sync
    status, archive/review stats, action buttons, folder shortcuts,
    month filter + ledger export, table — so at 1280x800 at least a
    dozen invoice rows are visible.
    """

    def __init__(self) -> None:
        super().__init__()
        self.invoice_root_path = PathSelector("发票主目录:")
        self.mail_status_bar = MailStatusBar()
        self.mail_dialog = MailManagerDialog()
        # Compatibility alias: the full sync panel lives inside the
        # manager dialog now, but callers/tests still reach it here.
        self.mail_panel = self.mail_dialog.panel
        self.summary_cards = SummaryCards()
        self.archive_stats_label = QLabel(
            "已归档 0 | 发票异常 0 | 其他票据 0 | 待识别 0 | 重复 0 | 其他附件 0"
        )
        self.dir_stats_label = QLabel("目录统计: -")

        self.scan_button = QPushButton("扫描待处理发票")
        self.preview_button = QPushButton("生成处理预览")
        self.evaluate_button = QPushButton("评估自动归档")
        self.execute_button = QPushButton("执行归档")
        self.duplicate_button = QPushButton("查看重复项")
        self.archive_non_invoice_button = QPushButton("归档非发票")
        self.review_button = QPushButton("审核选中项")
        self.view_pdf_button = QPushButton("查看PDF")
        self.import_button = QPushButton("导入PDF")
        self.open_pending_button = QPushButton("打开待处理目录")
        self.open_review_button = QPushButton("打开非发票目录")
        self.open_archive_button = QPushButton("打开归档目录")
        self.open_month_button = QPushButton("打开月份目录")
        self.open_report_button = QPushButton("打开报表目录")
        self.open_root_button = QPushButton("打开发票目录")
        self.open_logs_button = QPushButton("打开日志目录")

        button_row = QHBoxLayout()
        button_row.addWidget(self.scan_button)
        button_row.addWidget(self.preview_button)
        button_row.addWidget(self.evaluate_button)
        button_row.addWidget(self.execute_button)
        button_row.addWidget(self.duplicate_button)
        button_row.addWidget(self.archive_non_invoice_button)
        button_row.addWidget(self.review_button)
        button_row.addWidget(self.view_pdf_button)
        button_row.addWidget(self.import_button)

        folder_row = QHBoxLayout()
        folder_row.addWidget(self.open_pending_button)
        folder_row.addWidget(self.open_review_button)
        folder_row.addWidget(self.open_archive_button)
        folder_row.addWidget(self.open_month_button)
        folder_row.addWidget(self.open_report_button)
        folder_row.addWidget(self.open_root_button)
        folder_row.addWidget(self.open_logs_button)
        folder_row.addStretch(1)

        self.month_combo = QComboBox()
        self.month_combo.setEditable(False)
        self.month_combo.setMinimumWidth(110)
        self.export_ledger_button = QPushButton("导出月度台账")
        ledger_row = QHBoxLayout()
        ledger_row.addWidget(QLabel("月份:"))
        ledger_row.addWidget(self.month_combo)
        ledger_row.addWidget(self.export_ledger_button)
        ledger_row.addStretch(1)

        self.table_model = InvoiceTableModel()
        self.table_view = QTableView()
        self.table_view.setModel(self.table_model)
        self.table_view.setSelectionBehavior(QTableView.SelectRows)

        layout = QVBoxLayout(self)
        layout.addWidget(self.invoice_root_path)
        layout.addWidget(self.mail_status_bar)
        layout.addWidget(self.archive_stats_label)
        layout.addWidget(self.dir_stats_label)
        layout.addLayout(button_row)
        layout.addLayout(folder_row)
        layout.addLayout(ledger_row)
        layout.addWidget(self.summary_cards)
        layout.addWidget(self.table_view)
