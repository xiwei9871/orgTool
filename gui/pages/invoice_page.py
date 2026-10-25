"""Invoice management page."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from gui.models.invoice_table_model import InvoiceTableModel
from gui.pages.mail_panel import MailSyncPanel
from gui.widgets.path_selector import PathSelector
from gui.widgets.summary_cards import SummaryCards


class InvoicePage(QWidget):
    """Invoice processing controls and preview table."""

    def __init__(self) -> None:
        super().__init__()
        self.invoice_root_path = PathSelector("发票主目录:")
        self.mail_panel = MailSyncPanel()
        self.summary_cards = SummaryCards()

        self.scan_button = QPushButton("扫描待处理发票")
        self.preview_button = QPushButton("生成处理预览")
        self.execute_button = QPushButton("执行归档")
        self.duplicate_button = QPushButton("查看重复项")
        self.open_month_button = QPushButton("打开月份目录")
        self.open_report_button = QPushButton("打开报表目录")
        self.open_root_button = QPushButton("打开发票目录")
        self.open_logs_button = QPushButton("打开日志目录")

        button_row = QHBoxLayout()
        button_row.addWidget(self.scan_button)
        button_row.addWidget(self.preview_button)
        button_row.addWidget(self.execute_button)
        button_row.addWidget(self.duplicate_button)
        button_row.addWidget(self.open_month_button)
        button_row.addWidget(self.open_report_button)
        button_row.addWidget(self.open_root_button)
        button_row.addWidget(self.open_logs_button)

        self.table_model = InvoiceTableModel()
        self.table_view = QTableView()
        self.table_view.setModel(self.table_model)

        layout = QVBoxLayout(self)
        layout.addWidget(self.invoice_root_path)
        layout.addWidget(self.mail_panel)
        layout.addLayout(button_row)
        layout.addWidget(self.summary_cards)
        layout.addWidget(self.table_view)
