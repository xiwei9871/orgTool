"""Models for invoice extraction and processing."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class InvoiceRecord:
    """Structured invoice data used by later parsing and archive steps."""

    file_name: str
    file_path: str
    file_hash: str
    invoice_number: str = ""
    invoice_date: str = ""
    invoice_content: str = ""
    amount: float | None = None
    seller: str = ""
    buyer: str = ""
    tax_amount: float | None = None
    source_type: str = "pdf"
    doc_type: str = ""
    field_sources: dict = field(default_factory=dict)
    recognition_status: str = "pending"
    date_source: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TextExtractionResult:
    """The outcome of extracting text from a document."""

    success: bool
    text: str
    status: str
    message: str = ""


@dataclass(slots=True)
class DuplicateCheckResult:
    """The result of invoice duplicate analysis."""

    status: str
    reason: str
    matched_record_path: str = ""


@dataclass(slots=True)
class InvoicePreviewItem:
    """A preview row for invoice processing."""

    file_name: str
    source_path: str
    invoice_number: str
    invoice_date: str
    amount: float | None
    content: str
    duplicate_status: str
    target_path: str
    report_path: str
    month_key: str
    status: str
    remark: str
    is_skipped: bool
    skip_reason: str
    record: InvoiceRecord
