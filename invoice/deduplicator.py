"""Invoice duplicate detection."""

from __future__ import annotations

from invoice.metadata_store import InvoiceMetadataStore
from models.invoice import DuplicateCheckResult, InvoiceRecord


class InvoiceDeduplicator:
    """Check invoice records against known metadata."""

    def __init__(self, metadata_store: InvoiceMetadataStore) -> None:
        self.metadata_store = metadata_store

    def check(self, record: InvoiceRecord) -> DuplicateCheckResult:
        """Return duplicate status based on file hash and business fields."""
        if not record.invoice_number or record.amount is None:
            return DuplicateCheckResult("待确认", "missing invoice number or amount")

        for existing in self.metadata_store.load_records():
            # A stored record pointing at the very same file (same path
            # AND same hash) is this invoice itself — e.g. written by
            # save_manual_review before archive_confirmed runs.  Skipping
            # it prevents self-collision; a different file sharing the
            # hash is still a real strong duplicate.
            if (
                existing.file_hash
                and existing.file_hash == record.file_hash
                and existing.file_path == record.file_path
            ):
                continue
            if existing.file_hash and existing.file_hash == record.file_hash:
                return DuplicateCheckResult("强重复", "matching file hash", existing.file_path)
            if (
                existing.invoice_number
                and existing.invoice_number == record.invoice_number
                and existing.amount == record.amount
            ):
                return DuplicateCheckResult(
                    "强重复",
                    "matching invoice number and amount",
                    existing.file_path,
                )
            if existing.invoice_number and existing.invoice_number == record.invoice_number:
                return DuplicateCheckResult(
                    "疑似重复",
                    "matching invoice number",
                    existing.file_path,
                )

        return DuplicateCheckResult("新发票", "no duplicate evidence")
