"""Tests for monthly invoice Excel export."""

from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from invoice.excel_exporter import InvoiceExcelExporter
from models.invoice import InvoiceRecord


def test_excel_exporter_creates_monthly_ledger_with_summary(tmp_path: Path) -> None:
    """Exporter should write invoice rows and summary values into a workbook."""
    exporter = InvoiceExcelExporter()
    report_path = tmp_path / "发票台账_202603.xlsx"
    records = [
        InvoiceRecord(
            file_name="a.pdf",
            file_path="C:/archive/a.pdf",
            file_hash="hash-a",
            invoice_number="1001",
            invoice_date="2026-03-05",
            invoice_content="办公用品",
            amount=88.5,
            seller="京东",
            recognition_status="complete",
            date_source="content",
        ),
        InvoiceRecord(
            file_name="b.pdf",
            file_path="C:/archive/b.pdf",
            file_hash="hash-b",
            invoice_number="1002",
            invoice_date="2026-03-06",
            invoice_content="住宿",
            amount=120.0,
            seller="酒店",
            recognition_status="complete",
            date_source="content",
        ),
    ]

    exporter.export(report_path, records)

    workbook = load_workbook(report_path)
    sheet = workbook["台账"]

    assert sheet["A1"].value == "序号"
    assert sheet["B2"].value == "1001"
    assert sheet["E3"].value == 120.0
    assert sheet["A5"].value == "发票总数"
    assert sheet["B5"].value == 2
    assert sheet["A6"].value == "金额总计"
    assert sheet["B6"].value == 208.5
