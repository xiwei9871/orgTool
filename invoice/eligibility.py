"""Auto-archive eligibility evaluation (S3.3).

``recognition_status == "complete"`` alone is NOT permission to
auto-archive.  A record qualifies only when every hard condition
holds; otherwise it goes to the review queue with machine-readable
reason codes so the UI can explain exactly what is missing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from invoice.parser import _STRONG_AMOUNT_SOURCES
from models.invoice import InvoiceRecord

_STRONG_TEXT_SOURCES = {
    "label",
    "label_window",
    "dzfp_block",
    "filename_verified",
}

_REASON_TEXT = {
    "not_e_invoice": "文档类型不是电子发票",
    "not_complete": "识别状态不完整",
    "missing_number": "发票号码缺失",
    "weak_number": "发票号码仅有兜底证据",
    "bad_number_format": "发票号码格式非法",
    "missing_date": "开票日期缺失",
    "weak_date": "开票日期仅有兜底/文件属性证据",
    "bad_date_format": "开票日期格式非法",
    "missing_amount": "价税合计缺失",
    "weak_amount": "金额仅有兜底/窗口证据",
    "bad_amount": "金额超出可信范围",
    "tax_missing": "税额缺失或未经净+税=总额验证",
    "buyer_missing": "购买方缺失或不可信",
    "seller_missing": "销售方缺失或不可信",
    "duplicate_conflict": "存在重复冲突",
    "file_hash_missing": "文件哈希缺失",
    "file_unreadable": "PDF 无法读取或哈希不匹配",
    "review_flags": "存在待复核字段",
}


@dataclass
class ArchiveVerdict:
    """The auto-archive admission decision for one record."""

    eligible: bool
    reasons: list[str] = field(default_factory=list)

    def reason_texts(self) -> list[str]:
        return [_REASON_TEXT.get(r, r) for r in self.reasons]


def evaluate_eligibility(
    record: InvoiceRecord,
    duplicate_status: str,
    file_hash_ok: bool = True,
) -> ArchiveVerdict:
    """Decide whether a record may auto-archive.

    ``file_hash_ok`` is supplied by the caller after re-reading the PDF
    bytes and comparing SHA-256 — eligibility never trusts stale state.
    """
    reasons: list[str] = []
    src = record.field_sources or {}

    if record.doc_type != "e_invoice":
        reasons.append("not_e_invoice")
        return ArchiveVerdict(False, reasons)

    if record.recognition_status != "complete":
        reasons.append("not_complete")

    number = (record.invoice_number or "").strip()
    if not number:
        reasons.append("missing_number")
    elif src.get("number") not in _STRONG_TEXT_SOURCES:
        reasons.append("weak_number")
    if number and not re.fullmatch(r"[0-9A-Za-z]{8,20}", number):
        reasons.append("bad_number_format")

    invoice_date = (record.invoice_date or "").strip()
    if not invoice_date:
        reasons.append("missing_date")
    elif src.get("date") not in _STRONG_TEXT_SOURCES:
        reasons.append("weak_date")
    if invoice_date:
        try:
            parsed = date.fromisoformat(invoice_date)
            if not (2000 <= parsed.year <= 2100):
                reasons.append("bad_date_format")
        except ValueError:
            reasons.append("bad_date_format")

    if record.amount is None:
        reasons.append("missing_amount")
    elif record.amount <= 0 or record.amount > 10000:
        reasons.append("bad_amount")
    elif src.get("amount") not in _STRONG_AMOUNT_SOURCES:
        reasons.append("weak_amount")

    # Tax consistency: a verified amount already passed net+tax=total;
    # a present-but-unverified tax or a missing tax needs review.
    if record.tax_amount is None or src.get("amount") != "verified":
        reasons.append("tax_missing")

    if not (record.buyer or "").strip():
        reasons.append("buyer_missing")
    if not (record.seller or "").strip():
        reasons.append("seller_missing")

    if duplicate_status != "新发票":
        reasons.append("duplicate_conflict")

    if not record.file_hash:
        reasons.append("file_hash_missing")
    elif not file_hash_ok:
        reasons.append("file_unreadable")

    if record.review_fields:
        reasons.append("review_flags")

    return ArchiveVerdict(not reasons, reasons)
