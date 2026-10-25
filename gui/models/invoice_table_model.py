"""Qt table model for invoice preview rows."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from models.invoice import InvoicePreviewItem

INVOICE_HEADERS = [
    "文件名",
    "发票编号",
    "日期",
    "金额",
    "内容",
    "查重结果",
    "归档目标",
    "状态",
    "购买方",
    "税额",
    "备注",
]


class InvoiceTableModel(QAbstractTableModel):
    """Expose invoice preview rows to a QTableView."""

    def __init__(self, items: list[InvoicePreviewItem] | None = None) -> None:
        super().__init__()
        self._items = items or []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._items)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(INVOICE_HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        item = self._items[index.row()]
        values = [
            item.file_name,
            item.invoice_number,
            item.invoice_date,
            "" if item.amount is None else str(item.amount),
            item.content,
            item.duplicate_status,
            item.target_path,
            item.status,
            getattr(item.record, "buyer", "") if item.record else "",
            (
                ""
                if item.record is None or item.record.tax_amount is None
                else str(item.record.tax_amount)
            ),
            item.remark,
        ]
        return values[index.column()]

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return INVOICE_HEADERS[section]
        return section + 1

    def set_items(self, items: list[InvoicePreviewItem]) -> None:
        self.beginResetModel()
        self._items = items
        self.endResetModel()
