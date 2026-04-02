"""Compact summary widget."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget


class SummaryCards(QWidget):
    """Show a few lightweight summary counters."""

    def __init__(self) -> None:
        super().__init__()
        self.total_label = QLabel("总数: 0")
        self.actionable_label = QLabel("可处理: 0")
        self.skipped_label = QLabel("跳过: 0")

        layout = QHBoxLayout(self)
        layout.addWidget(self.total_label)
        layout.addWidget(self.actionable_label)
        layout.addWidget(self.skipped_label)
        layout.addStretch(1)

    def set_counts(self, total: int, actionable: int, skipped: int) -> None:
        self.total_label.setText(f"总数: {total}")
        self.actionable_label.setText(f"可处理: {actionable}")
        self.skipped_label.setText(f"跳过: {skipped}")
