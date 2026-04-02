"""Qt table model for desktop preview rows."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from models.desktop import PreviewItem

PREVIEW_HEADERS = ["文件名", "类型", "建议分类", "目标路径", "置信度", "状态"]


class PreviewTableModel(QAbstractTableModel):
    """Expose desktop preview rows to a QTableView."""

    def __init__(self, items: list[PreviewItem] | None = None) -> None:
        super().__init__()
        self._items = items or []

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._items)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(PREVIEW_HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        item = self._items[index.row()]
        values = [
            item.name,
            item.file_type,
            item.suggested_category,
            item.target_path,
            f"{item.confidence:.2f}",
            "跳过" if item.is_skipped else "待执行",
        ]
        return values[index.column()]

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return PREVIEW_HEADERS[section]
        return section + 1

    def set_items(self, items: list[PreviewItem]) -> None:
        self.beginResetModel()
        self._items = items
        self.endResetModel()
