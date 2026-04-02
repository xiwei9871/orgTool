"""Desktop organization page."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from gui.models.preview_table_model import PreviewTableModel
from gui.widgets.path_selector import PathSelector
from gui.widgets.summary_cards import SummaryCards


class DesktopPage(QWidget):
    """Desktop organization controls and preview table."""

    def __init__(self) -> None:
        super().__init__()
        self.desktop_path = PathSelector("当前桌面路径:")
        self.archive_path = PathSelector("当前归档目录:")
        self.summary_cards = SummaryCards()

        self.scan_button = QPushButton("扫描桌面")
        self.preview_button = QPushButton("生成预览")
        self.execute_button = QPushButton("执行整理")
        self.undo_button = QPushButton("撤销上一次整理")
        self.open_logs_button = QPushButton("打开日志目录")
        self.settings_button = QPushButton("打开设置")

        button_row = QHBoxLayout()
        button_row.addWidget(self.scan_button)
        button_row.addWidget(self.preview_button)
        button_row.addWidget(self.execute_button)
        button_row.addWidget(self.undo_button)
        button_row.addWidget(self.open_logs_button)
        button_row.addWidget(self.settings_button)

        self.table_model = PreviewTableModel()
        self.table_view = QTableView()
        self.table_view.setModel(self.table_model)

        layout = QVBoxLayout(self)
        layout.addWidget(self.desktop_path)
        layout.addWidget(self.archive_path)
        layout.addLayout(button_row)
        layout.addWidget(self.summary_cards)
        layout.addWidget(self.table_view)
