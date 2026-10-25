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


def test_s3_1_didi_spaced_labels_and_amount_before_currency(tmp_path: Path) -> None:
    """滴滴 layout: spaced 价税合计 label, amount before ¥, 合计 net+tax."""
    file_path = tmp_path / "didi.pdf"
    file_path.write_text("fake", encoding="utf-8")
    text = (
        "电子发票（普通发票） 发票号码 : 26317000003669102866 开票日期 : 2026年10月10日 "
        "合 计 43.20¥ 1.30¥ 价 税 合 计 （ 大 写 ） （ 小 写 ） 44.50¥肆拾肆圆伍角整"
    )
    record = InvoiceParser().parse(
        file_path=file_path, extracted_text=text,
        file_hash="h", modified_at=datetime(2026, 3, 6),
    )
    assert record.amount == 44.50
    assert record.tax_amount == 1.30
    assert record.field_sources["amount"] == "verified"
    assert record.recognition_status == "complete"


def test_s3_1_dzfp_values_block_and_parties(tmp_path: Path) -> None:
    """幔壳 layout: empty labels, values block after 开票人, 大写-adjacent total."""
    file_path = tmp_path / "dzfp_26352000002308138771_四川幔壳科技有限公司_20261008.pdf"
    file_path.write_text("fake", encoding="utf-8")
    text = (
        "电子发票（普通发票） 发票号码： 开票日期： 购 买 方 信 息 "
        "统一社会信用代码/纳税人识别号： 销 售 方 信 息 名称： 名称： "
        "价税合计（大写） （小写） 开票人： 26352000002308138771 2026年10月08日 "
        "四川幔壳科技有限公司 91510100MA6C5HHD7T 福建三简茶界科技有限公司 "
        "91350104MA33FNMH9G ¥87.61 ¥11.39 玖拾玖圆整 ¥99.00 范长妹"
    )
    record = InvoiceParser().parse(
        file_path=file_path, extracted_text=text,
        file_hash="h", modified_at=datetime(2026, 3, 6),
    )
    assert record.invoice_number == "26352000002308138771"
    assert record.invoice_date == "2026-10-08"
    assert record.amount == 99.00
    assert record.tax_amount == 11.39
    assert record.buyer == "四川幔壳科技有限公司"
    assert record.seller == "福建三简茶界科技有限公司"
    assert record.field_sources["amount"] == "verified"
    assert record.field_sources["number"] == "filename_verified"
    assert record.recognition_status == "complete"


def test_s3_1_amount_total_before_daxie(tmp_path: Path) -> None:
    """7102 layout: ¥total directly followed by 大写 chars."""
    file_path = tmp_path / "rent.pdf"
    file_path.write_text("fake", encoding="utf-8")
    text = (
        "电子发票（增值税专用发票） 开票人： 26317000003543633463 2026年10月22日 "
        "四川幔壳科技有限公司 91510100MA6C5HHD7T 北京神州汽车租赁有限公司 91310109 "
        "合 计 ¥274.34 ¥35.66 ¥310.00叁佰壹拾圆整"
    )
    record = InvoiceParser().parse(
        file_path=file_path, extracted_text=text,
        file_hash="h", modified_at=datetime(2026, 3, 6),
    )
    assert record.amount == 310.00
    assert record.tax_amount == 35.66
    assert record.field_sources["amount"] == "verified"


def test_s3_1_fallback_never_auto_confirms(tmp_path: Path) -> None:
    """A bare digit-run and unanchored amount must stay partial."""
    file_path = tmp_path / "mystery.pdf"
    file_path.write_text("fake", encoding="utf-8")
    text = "订单号 12345678901 总价 500.00 谢谢惠顾"
    record = InvoiceParser().parse(
        file_path=file_path, extracted_text=text,
        file_hash="h", modified_at=datetime(2026, 3, 6),
    )
    assert record.recognition_status == "partial"
    assert record.field_sources["number"] == "fallback"
    assert record.field_sources["amount"] == "fallback"


def test_s3_1_fragmented_amount_rejected(tmp_path: Path) -> None:
    """Broken '¥ 663.7 2' splits must not be read as the total."""
    file_path = tmp_path / "broken.pdf"
    file_path.write_text("fake", encoding="utf-8")
    text = (
        "发票号码：26442000001361572006 开票日期：2026年02月04日 "
        "合计 价税合计（大写） （小写） ¥ 663.7 2 ¥ 8 6.28 柒佰伍拾圆整 ¥ 7 50.00"
    )
    record = InvoiceParser().parse(
        file_path=file_path, extracted_text=text,
        file_hash="h", modified_at=datetime(2026, 3, 6),
    )
    assert record.amount is None or record.amount > 10000 or record.field_sources["amount"] not in ("label", "daxie", "verified")
    assert record.recognition_status == "partial"
