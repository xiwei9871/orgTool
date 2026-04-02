"""Tests for invoice deduplication."""

from __future__ import annotations

from pathlib import Path

from invoice.deduplicator import InvoiceDeduplicator
from invoice.metadata_store import InvoiceMetadataStore
from models.invoice import InvoiceRecord


def test_deduplicator_marks_hash_matches_as_strong_duplicates(tmp_path: Path) -> None:
    """Matching file hashes should be treated as strong duplicates."""
    store = InvoiceMetadataStore(tmp_path / "metadata")
    store.save_records(
        [
            InvoiceRecord(
                file_name="old.pdf",
                file_path="C:/archive/old.pdf",
                file_hash="same-hash",
                invoice_number="1001",
                amount=50.0,
                recognition_status="complete",
            )
        ]
    )

    result = InvoiceDeduplicator(store).check(
        InvoiceRecord(
            file_name="new.pdf",
            file_path="C:/pending/new.pdf",
            file_hash="same-hash",
            invoice_number="1002",
            amount=60.0,
            recognition_status="complete",
        )
    )

    assert result.status == "强重复"


def test_deduplicator_marks_business_duplicates_from_number_and_amount(
    tmp_path: Path,
) -> None:
    """Matching invoice number and amount should be a strong duplicate."""
    store = InvoiceMetadataStore(tmp_path / "metadata")
    store.save_records(
        [
            InvoiceRecord(
                file_name="old.pdf",
                file_path="C:/archive/old.pdf",
                file_hash="hash-a",
                invoice_number="INV-7788",
                amount=199.0,
                recognition_status="complete",
            )
        ]
    )

    result = InvoiceDeduplicator(store).check(
        InvoiceRecord(
            file_name="new.pdf",
            file_path="C:/pending/new.pdf",
            file_hash="hash-b",
            invoice_number="INV-7788",
            amount=199.0,
            recognition_status="complete",
        )
    )

    assert result.status == "强重复"


def test_deduplicator_returns_pending_when_information_is_incomplete(
    tmp_path: Path,
) -> None:
    """Incomplete invoice fields should return a review-needed result."""
    store = InvoiceMetadataStore(tmp_path / "metadata")
    result = InvoiceDeduplicator(store).check(
        InvoiceRecord(
            file_name="new.pdf",
            file_path="C:/pending/new.pdf",
            file_hash="hash-c",
            recognition_status="partial",
        )
    )

    assert result.status == "待确认"
