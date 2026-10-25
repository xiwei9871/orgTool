"""Document-type classification for downloaded PDFs.

Classifies a PDF by its extracted text layer — deliberately independent of
``invoice.parser`` so non-invoice documents are never forced through the
invoice regex pipeline (baseline audit: 16/20 non-invoices were mislabeled
``complete``).
"""

from __future__ import annotations

import re

DOC_E_INVOICE = "e_invoice"
DOC_TRAVEL_VOUCHER = "travel_voucher"
DOC_HOTEL_FOLIO = "hotel_folio"
DOC_OTHER = "other_pdf"
DOC_NEEDS_OCR = "needs_ocr"
DOC_UNKNOWN = "unknown"

MIN_TEXT_CHARS = 30

_INVOICE_RE = re.compile(r"电子发票|数电票|全电发票|增值税.{0,4}发票|发票号码")
_VOUCHER_RE = re.compile(
    r"行程单|行程报销|报销单|报销凭证|明细单|退票费|改签费|ITINERARY|行程编号",
    re.IGNORECASE,
)
_FOLIO_RE = re.compile(r"结账单|对账单|离店日期|入住日期|房费|FOLIO|guest\s*folio", re.IGNORECASE)


def classify_pdf_text(text: str) -> str:
    """Classify a PDF by its extracted text.

    Order matters: a 报销凭证/行程单 carrying a real 发票号码 is still an
    e-invoice; image-only PDFs cannot be classified from text at all.
    """
    flat = re.sub(r"\s+", " ", text or "").strip()
    if len(flat) < MIN_TEXT_CHARS:
        return DOC_NEEDS_OCR
    if _INVOICE_RE.search(flat) and (
        re.search(r"发票号码|发票代码", flat) or "电子发票" in flat or "数电" in flat
    ):
        return DOC_E_INVOICE
    if _FOLIO_RE.search(flat):
        return DOC_HOTEL_FOLIO
    if _VOUCHER_RE.search(flat):
        return DOC_TRAVEL_VOUCHER
    if "发票" in flat:
        return DOC_UNKNOWN
    return DOC_OTHER


_INVOICE_LINK_RE = re.compile(
    r"https?://[^\s<>\"'\)]+", re.IGNORECASE
)
_INVOICE_LINK_HINT = re.compile(
    r"发票|fapiao|invoice|dzfp|fpdz|fpfw|e-?invoice", re.IGNORECASE
)


def find_invoice_links(text: str) -> list[str]:
    """Extract URLs that look like electronic-invoice download links.

    Used for messages with no PDF attachment — the link is recorded for
    manual review, never fetched automatically.
    """
    links: list[str] = []
    for match in _INVOICE_LINK_RE.finditer(text or ""):
        url = match.group(0).rstrip(".,;:!?]）】")
        if _INVOICE_LINK_HINT.search(url) and url not in links:
            links.append(url)
    return links
