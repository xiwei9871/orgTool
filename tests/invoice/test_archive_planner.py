"""Tests for invoice archive path planning."""

from __future__ import annotations

from pathlib import Path

from config.schema import InvoiceConfig
from invoice.archive_planner import InvoiceArchivePlanner
from models.invoice import InvoiceRecord


def test_archive_planner_builds_month_archive_target(tmp_path: Path) -> None:
    """New invoices should route into the configured month folder."""
    config = InvoiceConfig(root_dir=str(tmp_path))
    record = InvoiceRecord(
        file_name="京东发票.pdf",
        file_path=str(tmp_path / "发票归档_待处理" / "京东发票.pdf"),
        file_hash="hash-001",
        invoice_date="2026-03-05",
        recognition_status="complete",
    )

    plan = InvoiceArchivePlanner().plan(record, "新发票", config)

    assert plan.target_path == str(
        tmp_path / "按月份归档" / "发票202603" / "京东发票.pdf"
    )
    assert plan.report_path == str(tmp_path / "导出报表" / "发票台账_202603.xlsx")


def test_archive_planner_routes_strong_duplicates_to_duplicate_dir(
    tmp_path: Path,
) -> None:
    """Strong duplicates should route to the duplicate directory when enabled."""
    config = InvoiceConfig(root_dir=str(tmp_path), move_strong_duplicates=True)
    record = InvoiceRecord(
        file_name="重复发票.pdf",
        file_path=str(tmp_path / "发票归档_待处理" / "重复发票.pdf"),
        file_hash="hash-002",
        invoice_date="2026-03-05",
        recognition_status="complete",
    )

    plan = InvoiceArchivePlanner().plan(record, "强重复", config)

    assert plan.target_path == str(tmp_path / "重复发票" / "重复发票.pdf")
