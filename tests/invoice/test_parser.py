"""Tests for invoice field parsing."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from invoice.parser import InvoiceParser


def test_invoice_parser_extracts_number_date_and_amount_from_text(
    tmp_path: Path,
) -> None:
    """Parser should extract key invoice fields from PDF text."""
    file_path = tmp_path / "京东发票.pdf"
    file_path.write_text("fake", encoding="utf-8")
    text = "\n".join(
        [
            "发票号码：12345678",
            "开票日期：2026-03-05",
            "发票内容：办公用品",
            "价税合计：88.50",
        ]
    )

    record = InvoiceParser().parse(
        file_path=file_path,
        extracted_text=text,
        file_hash="hash-001",
        modified_at=datetime(2026, 3, 6, 12, 0, 0),
    )

    assert record.invoice_number == "12345678"
    assert record.invoice_date == "2026-03-05"
    assert record.invoice_content == "办公用品"
    assert record.amount == 88.50
    assert record.date_source == "content"


def test_invoice_parser_falls_back_to_filename_and_mtime_for_date(
    tmp_path: Path,
) -> None:
    """Date should fall back from content to filename, then modified time."""
    file_with_filename_date = tmp_path / "发票_20260301.pdf"
    file_with_filename_date.write_text("fake", encoding="utf-8")

    record_from_filename = InvoiceParser().parse(
        file_path=file_with_filename_date,
        extracted_text="发票号码：99887766",
        file_hash="hash-002",
        modified_at=datetime(2026, 3, 6, 12, 0, 0),
    )

    assert record_from_filename.invoice_date == "2026-03-01"
    assert record_from_filename.date_source == "filename"

    file_with_mtime = tmp_path / "未知日期发票.pdf"
    file_with_mtime.write_text("fake", encoding="utf-8")
    record_from_mtime = InvoiceParser().parse(
        file_path=file_with_mtime,
        extracted_text="发票号码：55667788",
        file_hash="hash-003",
        modified_at=datetime(2026, 2, 28, 18, 30, 0),
    )

    assert record_from_mtime.invoice_date == "2026-02-28"
    assert record_from_mtime.date_source == "modified_time"


def test_invoice_parser_handles_line_broken_invoice_fields(tmp_path: Path) -> None:
    """Parser should recover invoice number, date, and total amount from layout-broken text."""
    file_path = tmp_path / "sample.pdf"
    file_path.write_text("fake", encoding="utf-8")
    text = (
        "电子发票（普通发票） 发票号码： | 开票日期： | 合计 | 价税合计（大写） （小写） | "
        "25362000000050138643 | 2025年05月26日 | ¥ 95.05 ¥ 0.95 | 玖拾陆圆整 ¥ 96.00"
    )

    record = InvoiceParser().parse(
        file_path=file_path,
        extracted_text=text,
        file_hash="hash-004",
        modified_at=datetime(2026, 3, 6, 12, 0, 0),
    )

    assert record.invoice_number == "25362000000050138643"
    assert record.invoice_date == "2025-05-26"
    assert record.amount == 96.00
    assert record.recognition_status == "complete"


def test_invoice_parser_handles_small_amount_marker_pattern(tmp_path: Path) -> None:
    """Parser should read the final amount from the 小写 marker pattern."""
    file_path = tmp_path / "mobile_invoice.pdf"
    file_path.write_text("fake", encoding="utf-8")
    text = (
        "电子发票（普通发票） 发票号码：25517000000437567850 "
        "开票日期：2025年10月24日 "
        "价税合计（大写） 贰佰肆拾捌圆整 （小写）¥248.00"
    )

    record = InvoiceParser().parse(
        file_path=file_path,
        extracted_text=text,
        file_hash="hash-005",
        modified_at=datetime(2026, 3, 6, 12, 0, 0),
    )

    assert record.invoice_number == "25517000000437567850"
    assert record.invoice_date == "2025-10-24"
    assert record.amount == 248.00


def test_invoice_parser_ignores_billing_period_numbers_after_total(tmp_path: Path) -> None:
    """Parser should prefer the currency amount over trailing billing period digits."""
    file_path = tmp_path / "carrier_invoice.pdf"
    file_path.write_text("fake", encoding="utf-8")
    text = (
        "开票人: 成都移动 电子发票（普通发票） 发票号码：25517000000437567850 "
        "开票日期：2025年10月24日 合计 ¥248.00 价税合计（大写） 贰佰肆拾捌圆整 （小写）¥248.00 "
        "备注 电话号码:15982375981 账号号码:11911126747189 计费周期:202506"
    )

    record = InvoiceParser().parse(
        file_path=file_path,
        extracted_text=text,
        file_hash="hash-006",
        modified_at=datetime(2026, 3, 6, 12, 0, 0),
    )

    assert record.amount == 248.00


def test_invoice_parser_ignores_long_identifiers_after_total(tmp_path: Path) -> None:
    """Parser should not treat invoice codes or tax IDs as the total amount."""
    file_path = tmp_path / "service_invoice.pdf"
    file_path.write_text("fake", encoding="utf-8")
    text = (
        "发票号码：220201102025515693 开票日期：2025年04月04日 价税合计（大写） （小写） "
        "壹佰玖拾捌圆整 ¥198.00 186.79¥ 11.21¥ 25117000000354834627 "
        "四川帛壳科技有限公司 91510100MA6C5HHD7T"
    )

    record = InvoiceParser().parse(
        file_path=file_path,
        extracted_text=text,
        file_hash="hash-007",
        modified_at=datetime(2026, 3, 6, 12, 0, 0),
    )

    assert record.amount == 198.00


def test_invoice_parser_marks_outlier_amount_for_manual_review(tmp_path: Path) -> None:
    """Parser should not auto-accept clearly abnormal totals from broken PDF layouts."""
    file_path = tmp_path / "broken_layout_invoice.pdf"
    file_path.write_text("fake", encoding="utf-8")
    text = (
        "电子发票（普通发票） 发票号码：26442000001361572006 开票日期：2026年02月04日 "
        "合计 价税合计（大写） （小写） ¥ 663.7 2 ¥ 8 6.28 "
        "柒佰伍拾圆整 ¥ 7 50.00 经营租赁 租车费 13%次 663.7 2 8 6.28663.7 21"
    )

    record = InvoiceParser().parse(
        file_path=file_path,
        extracted_text=text,
        file_hash="hash-008",
        modified_at=datetime(2026, 3, 6, 12, 0, 0),
    )

    assert record.amount is None
    assert record.recognition_status == "partial"
