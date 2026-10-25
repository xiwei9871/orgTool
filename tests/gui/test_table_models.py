"""Tests for Qt table models used by the GUI."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from gui.models.invoice_table_model import InvoiceTableModel
from gui.models.preview_table_model import PreviewTableModel
from models.desktop import PreviewItem
from models.invoice import InvoicePreviewItem, InvoiceRecord

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app() -> QApplication:
    app = QApplication.instance()
    return app if app is not None else QApplication(sys.argv)


def test_preview_table_model_exposes_expected_columns() -> None:
    """The desktop preview model should expose the expected table structure."""
    _app()
    model = PreviewTableModel(
        [
            PreviewItem(
                name="resume.pdf",
                source_path="C:/Desktop/resume.pdf",
                file_type="file",
                suggested_category="简历",
                target_path="C:/Desktop/桌面整理/简历/resume.pdf",
                confidence=0.92,
                reason="keyword: resume",
                is_skipped=False,
                skip_reason="",
                subcategory="",
            )
        ]
    )

    assert model.columnCount() == 6
    assert model.data(model.index(0, 0), Qt.DisplayRole) == "resume.pdf"
    assert model.data(model.index(0, 2), Qt.DisplayRole) == "简历"
    assert model.data(model.index(0, 5), Qt.DisplayRole) == "待执行"
    assert model.headerData(0, Qt.Horizontal, Qt.DisplayRole) == "文件名"
    assert model.headerData(5, Qt.Horizontal, Qt.DisplayRole) == "状态"


def test_invoice_table_model_maps_invoice_preview_rows() -> None:
    """The invoice table model should expose invoice preview data."""
    _app()
    model = InvoiceTableModel(
        [
            InvoicePreviewItem(
                file_name="invoice.pdf",
                source_path="C:/pending/invoice.pdf",
                invoice_number="1001",
                invoice_date="2026-03-05",
                amount=88.5,
                content="办公用品",
                duplicate_status="新发票",
                target_path="C:/archive/发票202603/invoice.pdf",
                report_path="C:/reports/发票台账_202603.xlsx",
                month_key="202603",
                status="complete",
                remark="no duplicate evidence",
                is_skipped=False,
                skip_reason="",
                record=InvoiceRecord(
                    file_name="invoice.pdf",
                    file_path="C:/pending/invoice.pdf",
                    file_hash="hash-1",
                ),
            )
        ]
    )

    assert model.columnCount() == 11
    assert model.data(model.index(0, 0), Qt.DisplayRole) == "invoice.pdf"
    assert model.data(model.index(0, 1), Qt.DisplayRole) == "1001"
    assert model.data(model.index(0, 5), Qt.DisplayRole) == "新发票"
    assert model.headerData(0, Qt.Horizontal, Qt.DisplayRole) == "文件名"
    assert model.headerData(6, Qt.Horizontal, Qt.DisplayRole) == "归档目标"
    assert model.headerData(8, Qt.Horizontal, Qt.DisplayRole) == "购买方"
    assert model.headerData(9, Qt.Horizontal, Qt.DisplayRole) == "税额"
