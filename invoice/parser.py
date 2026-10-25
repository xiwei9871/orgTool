"""Rule-based invoice field extraction with per-field evidence tracking.

Every extracted field records its evidence source in
``InvoiceRecord.field_sources``.  Only fields anchored to a real label
(``label``), the 大写/小写 amount adjacency (``daxie``), or a verified
net+tax cross-check (``verified``) may auto-confirm an invoice as
``complete``.  Values produced by unconstrained fallbacks are still
populated for the reviewer, but they never yield ``complete`` on their
own — this prevents the S3 baseline failure where the "largest amount
anywhere" or "first 8+ digit run" silently masqueraded as recognized.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from models.invoice import InvoiceRecord

MAX_AUTOMATIC_AMOUNT = 10000.0

# Evidence levels that allow a field to count toward auto-confirmation.
# "label_window" counts as strong for number/date where the label is
# physically present and the value follows inside a bounded window —
# anchored evidence, unlike the unconstrained "fallback" scans.  For
# the amount it is not sufficient: a window's largest ¥ value can still
# be a line-item price, so amount requires the 小写 label, 大写
# adjacency, or a verified net+tax cross-check.
_STRONG_SOURCES = {
    "label",
    "label_window",
    "daxie",
    "verified",
    "dzfp_block",
    "filename_verified",
}
_STRONG_AMOUNT_SOURCES = {"label", "daxie", "verified"}

_DAXIE_CHARS = "零壹贰叁肆伍陆柒捌玖拾佰仟万亿圆元角分整"


class InvoiceParser:
    """Extract invoice metadata from text, filename, and timestamps."""

    def parse(
        self,
        file_path: Path,
        extracted_text: str,
        file_hash: str,
        modified_at: datetime,
    ) -> InvoiceRecord:
        """Parse invoice fields, recording the evidence for each value."""
        normalized_text = _normalize_text(extracted_text)
        # A second pass where spaced-out label keywords are joined so
        # regexes can anchor on them regardless of PDF column layout.
        label_text = _collapse_label_spacing(normalized_text)
        sources: dict[str, str] = {}

        invoice_number, sources["number"] = _extract_invoice_number(
            label_text, file_path.name
        )

        invoice_date, sources["date"] = _extract_invoice_date(label_text)
        if not invoice_date:
            invoice_date = _extract_date_from_filename(file_path.name)
            sources["date"] = "filename" if invoice_date else ""
        if not invoice_date:
            invoice_date = modified_at.strftime("%Y-%m-%d")
            sources["date"] = "modified_time"

        invoice_content, sources["content"] = _extract_invoice_content(
            label_text
        )

        amount, sources["amount"], amount_detail = _extract_total_amount(
            label_text
        )
        if amount is not None and amount > MAX_AUTOMATIC_AMOUNT:
            amount, sources["amount"] = None, "over_cap"

        tax_amount, sources["tax"] = _extract_tax_amount(
            label_text, amount_detail
        )
        # Cross-check: net + tax found on the 合计 row should equal the
        # 小写 total.  Agreement upgrades the amount to "verified".
        if (
            amount is not None
            and amount_detail.get("net") is not None
            and tax_amount is not None
            and abs(amount_detail["net"] + tax_amount - amount) < 0.005
        ):
            sources["amount"] = "verified"

        buyer, seller, sources["buyer"], sources["seller"] = _extract_parties(
            label_text, file_path.name
        )

        recognition_status = (
            "complete"
            if invoice_number
            and invoice_date
            and amount is not None
            and sources["number"] in _STRONG_SOURCES
            and sources["date"] in _STRONG_SOURCES
            and sources["amount"] in _STRONG_AMOUNT_SOURCES
            else "partial"
        )

        return InvoiceRecord(
            file_name=file_path.name,
            file_path=str(file_path),
            file_hash=file_hash,
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            invoice_content=invoice_content,
            amount=amount,
            seller=seller,
            buyer=buyer,
            tax_amount=tax_amount,
            recognition_status=recognition_status,
            date_source=(
                "content"
                if sources["date"] in ("label", "label_window", "dzfp_block")
                else sources["date"]
            ),
            field_sources=sources,
        )


def _normalize_text(text: str) -> str:
    """Flatten extracted PDF text into a regex-friendly form."""
    normalized = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    normalized = normalized.replace("|", " ").replace("　", " ")
    return re.sub(r"\s+", " ", normalized).strip()


_SPACED_LABELS = (
    ("价税合计", r"价\s*税\s*合\s*计"),
    ("（小写）", r"[（(]\s*小\s*写\s*[）)]"),
    ("（大写）", r"[（(]\s*大\s*写\s*[）)]"),
    ("发票号码", r"发\s*票\s*号\s*码"),
    ("开票日期", r"开\s*票\s*日\s*期"),
    ("发票内容", r"发\s*票\s*内\s*容"),
    ("项目名称", r"项\s*目\s*名\s*称"),
    ("购买方", r"购\s*买\s*方"),
    ("销售方", r"销\s*售\s*方"),
    ("名 称", r"名\s*称"),
    ("合计", r"(?<!价税)合\s*计"),
    ("税额", r"税\s*额"),
)


def _collapse_label_spacing(text: str) -> str:
    """Join spaced-out label keywords so anchors survive column layouts."""
    collapsed = text
    for canonical, spaced in _SPACED_LABELS:
        collapsed = re.sub(spaced, canonical, collapsed)
    return collapsed


def _extract_invoice_number(text: str, filename: str) -> tuple[str, str]:
    """Extract invoice number; sources: label, label_window, fallback."""
    direct_match = re.search(
        r"(?:发票号码|发票编号)\s*[:：]?\s*([A-Za-z0-9-]{6,})",
        text,
        re.IGNORECASE,
    )
    if direct_match:
        return direct_match.group(1).strip(), "label"

    for label in ("发票号码", "发票编号"):
        window = _window_after_label(text, label, 120)
        match = re.search(r"\b([0-9]{8,20})\b", window)
        if match:
            number = match.group(1)
            # dzfp filenames embed the invoice number — agreement is
            # independent evidence strong enough for auto-confirmation.
            if number in filename:
                return number, "filename_verified"
            return number, "label_window"

    block = _dzfp_values_block(text)
    if block.get("number"):
        number = block["number"]
        if number in filename:
            return number, "filename_verified"
        return number, "dzfp_block"

    fallback_match = re.search(r"\b([0-9]{8,20})\b", text)
    if not fallback_match:
        return "", ""
    number = fallback_match.group(1)
    if number in filename:
        return number, "filename_verified"
    return number, "fallback"


def _extract_invoice_date(text: str) -> tuple[str, str]:
    """Extract invoice date; sources: label, label_window, fallback."""
    direct_match = re.search(
        r"开票日期\s*[:：]?\s*((?:20\d{2})[年/-]\d{1,2}[月/-]\d{1,2}日?)",
        text,
        re.IGNORECASE,
    )
    if direct_match:
        return _normalize_date(direct_match.group(1)), "label"

    window = _window_after_label(text, "开票日期", 80)
    if window:
        match = re.search(r"((?:20\d{2})[年/-]\d{1,2}[月/-]\d{1,2}日?)", window)
        if match:
            return _normalize_date(match.group(1)), "label_window"

    block = _dzfp_values_block(text)
    if block.get("date"):
        return _normalize_date(block["date"]), "dzfp_block"

    match = re.search(r"((?:20\d{2})[年/-]\d{1,2}[月/-]\d{1,2}日?)", text)
    if match:
        return _normalize_date(match.group(1)), "fallback"
    return "", ""


def _dzfp_values_block(text: str) -> dict[str, str]:
    """Parse the 数电票 values block: invoice number + 开票日期 adjacent.

    On 数电票 the empty 发票号码/开票日期 labels cluster in the header
    while their values appear together as `<number> <YYYY年M月D日>` —
    either right after 开票人 or at the head of the values block.  That
    number+date adjacency is itself the structural anchor (a bare
    digit-run or bare date alone would not qualify).
    """
    for pattern in (
        r"开票人[：:]\s*(?:[^\s]{0,10}\s+)?([0-9]{8,20})\s+"
        r"((?:20\d{2})年\d{1,2}月\d{1,2}日)",
        r"(?<![0-9])([0-9]{8,20})\s+((?:20\d{2})年\d{1,2}月\d{1,2}日)",
    ):
        m = re.search(pattern, text)
        if m:
            return {"number": m.group(1), "date": m.group(2)}
    return {}


def _extract_invoice_content(text: str) -> tuple[str, str]:
    """Extract invoice content; source label when anchored."""
    match = re.search(
        r"发票内容\s*[:：]?\s*(.+?)\s*(?:销售方|购买方|价税合计|开票日期|$)",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip(), "label"
    # 数电票 item column: first *category*item token under 项目名称.
    item = re.search(r"\*[^*\s]+\*[^¥￥\s]+", text)
    if item:
        return item.group(0).strip(), "label_window"
    return "", ""


_AMOUNT = r"[¥￥]?\s*(-?[0-9]+\.[0-9]{1,2})\s*[¥￥]?"


def _extract_total_amount(
    text: str,
) -> tuple[float | None, str, dict[str, float | None]]:
    """Extract 价税合计; returns (amount, source, detail).

    detail carries the 合计-row net/tax when found, for cross-checks.
    """
    detail: dict[str, float | None] = {"net": None, "tax": None}

    # 合计 row: 合计 <net>¥ <tax>¥ — two adjacent money values.
    heji = re.search(r"合计\s+" + _AMOUNT + r"\s+" + _AMOUNT, text)
    if heji:
        detail["net"], detail["tax"] = float(heji.group(1)), float(
            heji.group(2)
        )
    else:
        # Any adjacent ¥net ¥tax pair (before or after the 大写/total).
        pair = re.search(
            r"[¥￥]\s*([0-9]+\.[0-9]{1,2})\s*[¥￥]\s*([0-9]+\.[0-9]{1,2})",
            text,
        )
        if pair:
            detail["net"], detail["tax"] = float(pair.group(1)), float(
                pair.group(2)
            )

    # 1a) Direct label adjacency: 价税合计[:：] N  or  （小写） N.
    # A digit separated only by spaces around the match means the PDF
    # split the value apart ("¥ 663.7 2", "¥ 8 6.28") — reject
    # fragmented numbers rather than trusting a truncated total.
    def _whole_number(m: re.Match) -> bool:
        before = text[max(0, m.start(1) - 6) : m.start(1)]
        after = text[m.end(1) : m.end(1) + 6]
        if re.search(r"[0-9]\s*$", before):
            return False
        return not re.match(r"\s*[0-9]", after)

    for pattern in (
        r"价税合计\s*[:：]\s*" + _AMOUNT,
        r"（小写）\s*" + _AMOUNT,
    ):
        m = re.search(pattern, text)
        if m and _whole_number(m):
            return float(m.group(1)), "label", detail

    # 2) 大写 words adjacent to the 小写 ¥ amount (either order, and the
    # ¥ may sit before or after the digits).
    m = re.search(
        r"[" + _DAXIE_CHARS + r"]{2,}\s*[¥￥]?\s*([0-9]+\.[0-9]{1,2})", text
    )
    if m and _whole_number(m):
        return float(m.group(1)), "daxie", detail
    m = re.search(
        r"[¥￥]?\s*([0-9]+\.[0-9]{1,2})\s*[¥￥]?\s*[" + _DAXIE_CHARS + r"]{2,}",
        text,
    )
    if m and _whole_number(m):
        return float(m.group(1)), "daxie", detail

    # 3) 价税合计 label window — largest ¥ amount nearby.
    window = _window_after_label(text, "价税合计", 120)
    amounts = _find_amount_candidates(window)
    if amounts:
        return float(max(amounts, key=float)), "label_window", detail

    # 4) Unanchored fallback — recorded but never auto-confirms.
    amounts = _find_amount_candidates(text)
    if amounts:
        return float(max(amounts, key=float)), "fallback", detail
    return None, "", detail


def _extract_tax_amount(
    text: str, detail: dict[str, float | None]
) -> tuple[float | None, str]:
    """Extract total tax; prefers the verified 合计 row pair."""
    if detail.get("tax") is not None:
        return detail["tax"], "label_window"
    m = re.search(r"税额\s*[:：]?\s*" + _AMOUNT, text)
    if m:
        return float(m.group(1)), "label"
    return None, ""


def _extract_parties(
    text: str, filename: str
) -> tuple[str, str, str, str]:
    """Extract buyer/seller from 名称： value pairs.

    On 数电票 the values block emits buyer name+税号 first, then seller —
    matching observed layouts.  Confidence upgrades when one party name
    also appears in the filename (dzfp_<num>_<buyer>_<ts>.pdf).
    """
    pairs = re.findall(
        r"名 称\s*[:：]\s*([^\s名]+?)\s*"
        r"(?:统一社会信用代码|纳税人识别号)[:：/]*\s*([0-9A-Z]{15,20})?",
        text,
    )
    names = [n for n, _ in pairs if n]
    if not names:
        # values-block form: two "公司 税号" pairs before the amounts
        m = re.findall(
            r"([一-龥]{4,30}?(?:公司|中心|事务所|部))\s+([0-9A-Z]{15,20})",
            text,
        )
        names = [n for n, _ in m]
    buyer = names[0] if names else ""
    seller = names[1] if len(names) > 1 else ""
    if not buyer and not seller:
        return "", "", "", ""
    if buyer and buyer in filename:
        return buyer, seller, "filename_verified", "order_pair"
    return buyer, seller, "order_pair", "order_pair"


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
