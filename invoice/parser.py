"""Rule-based invoice field extraction."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from models.invoice import InvoiceRecord

MAX_AUTOMATIC_AMOUNT = 10000.0


class InvoiceParser:
    """Extract invoice metadata from text, filename, and timestamps."""

    def parse(
        self,
        file_path: Path,
        extracted_text: str,
        file_hash: str,
        modified_at: datetime,
    ) -> InvoiceRecord:
        """Parse invoice fields with conservative fallback logic."""
        normalized_text = _normalize_text(extracted_text)
        invoice_number = _extract_invoice_number(normalized_text)
        invoice_date = _extract_invoice_date(normalized_text)
        date_source = "content" if invoice_date else ""

        if not invoice_date:
            invoice_date = _extract_date_from_filename(file_path.name)
            if invoice_date:
                date_source = "filename"

        if not invoice_date:
            invoice_date = modified_at.strftime("%Y-%m-%d")
            date_source = "modified_time"

        invoice_content = _extract_invoice_content(normalized_text)
        amount_text = _extract_invoice_amount(normalized_text)
        amount = float(amount_text) if amount_text else None
        if amount is not None and amount > MAX_AUTOMATIC_AMOUNT:
            amount = None
        recognition_status = (
            "complete" if invoice_number and invoice_date and amount is not None else "partial"
        )

        return InvoiceRecord(
            file_name=file_path.name,
            file_path=str(file_path),
            file_hash=file_hash,
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            invoice_content=invoice_content,
            amount=amount,
            recognition_status=recognition_status,
            date_source=date_source,
        )


def _normalize_text(text: str) -> str:
    """Flatten extracted PDF text into a regex-friendly form."""
    normalized = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    normalized = normalized.replace("|", " ").replace("\u3000", " ")
    return re.sub(r"\s+", " ", normalized).strip()


def _extract_invoice_number(text: str) -> str:
    """Extract invoice number near invoice labels, tolerating broken layouts."""
    direct_match = re.search(
        r"(?:发票号码|发票编号)\s*[:：]?\s*([A-Za-z0-9-]{6,})",
        text,
        re.IGNORECASE,
    )
    if direct_match:
        return direct_match.group(1).strip()

    for label in ("发票号码", "发票编号"):
        window = _window_after_label(text, label, 120)
        match = re.search(r"\b([0-9]{8,20})\b", window)
        if match:
            return match.group(1)

    fallback_match = re.search(r"\b([0-9]{8,20})\b", text)
    return fallback_match.group(1) if fallback_match else ""


def _extract_invoice_date(text: str) -> str:
    """Extract and normalize invoice date from labeled content."""
    direct_match = re.search(
        r"开票日期\s*[:：]?\s*((?:20\d{2})[年/-]\d{1,2}[月/-]\d{1,2}日?)",
        text,
        re.IGNORECASE,
    )
    if direct_match:
        return _normalize_date(direct_match.group(1))

    window = _window_after_label(text, "开票日期", 80)
    if window:
        match = re.search(r"((?:20\d{2})[年/-]\d{1,2}[月/-]\d{1,2}日?)", window)
        if match:
            return _normalize_date(match.group(1))

    match = re.search(r"((?:20\d{2})[年/-]\d{1,2}[月/-]\d{1,2}日?)", text)
    return _normalize_date(match.group(1)) if match else ""


def _extract_invoice_content(text: str) -> str:
    """Extract invoice content if the label exists."""
    match = re.search(
        r"发票内容\s*[:：]?\s*(.+?)\s*(?:销售方|购买方|价税合计|开票日期|$)",
        text,
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def _extract_invoice_amount(text: str) -> str:
    """Extract the final payable amount, preferring markers near the total."""
    labeled_amount = _extract_amount_near_markers(
        text,
        markers=("（小写）", "(小写)", "小写", "价税合计（大写）", "价税合计", "合计"),
        window_size=120,
    )
    if labeled_amount:
        return labeled_amount

    fallback_amounts = _find_amount_candidates(text)
    return max(fallback_amounts, key=float) if fallback_amounts else ""


def _extract_amount_near_markers(
    text: str,
    markers: tuple[str, ...],
    window_size: int,
) -> str:
    """Return the last amount found shortly after any marker."""
    for marker in markers:
        for match in re.finditer(re.escape(marker), text):
            window = text[match.end() : match.end() + window_size]
            amounts = _find_amount_candidates(window)
            if amounts:
                return max(amounts, key=float)
    return ""


def _find_amount_candidates(text: str) -> list[str]:
    """Find values that actually look like money, excluding long identifiers."""
    candidates: list[str] = []
    patterns = (
        r"[¥￥]\s*([0-9]+\.[0-9]{1,2})",
        r"(?<![0-9A-Za-z])([0-9]+\.[0-9]{1,2})\s*[¥￥]",
        r"(?<![0-9A-Za-z])([0-9]+\.[0-9]{1,2})(?![0-9A-Za-z])",
    )
    for pattern in patterns:
        for value in re.findall(pattern, text):
            if value not in candidates:
                candidates.append(value)
    return candidates


def _window_after_label(text: str, label: str, window_size: int) -> str:
    """Return a small slice of text immediately after a label."""
    match = re.search(re.escape(label), text, re.IGNORECASE)
    if not match:
        return ""
    return text[match.end() : match.end() + window_size]


def _extract_date_from_filename(filename: str) -> str:
    """Extract a YYYY-MM-DD date from common filename patterns."""
    match = re.search(r"(20\d{2})[-_/]?(\d{2})[-_/]?(\d{2})", filename)
    if not match:
        return ""
    year, month, day = match.groups()
    return f"{year}-{month}-{day}"


def _normalize_date(value: str) -> str:
    """Normalize invoice date strings into YYYY-MM-DD."""
    match = re.search(r"(20\d{2})\s*[年/-]\s*(\d{1,2})\s*[月/-]\s*(\d{1,2})", value)
    if not match:
        return value.replace("/", "-").strip()
    year, month, day = match.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}"
