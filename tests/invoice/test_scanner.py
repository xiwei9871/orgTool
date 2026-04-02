"""Tests for invoice intake scanning and hashing."""

from __future__ import annotations

from pathlib import Path

from invoice.scanner import InvoiceScanner
from utils.file_hash import compute_file_hash


def test_invoice_scanner_enumerates_pdf_files(tmp_path: Path) -> None:
    """The invoice scanner should return PDF files from the pending directory."""
    pending_dir = tmp_path / "发票归档_待处理"
    pending_dir.mkdir()
    (pending_dir / "invoice1.pdf").write_text("pdf", encoding="utf-8")
    (pending_dir / "invoice2.PDF").write_text("pdf", encoding="utf-8")
    (pending_dir / "notes.txt").write_text("ignore", encoding="utf-8")

    results = InvoiceScanner().scan_pending_dir(pending_dir)

    assert [path.name for path in results] == ["invoice1.pdf", "invoice2.PDF"]


def test_compute_file_hash_returns_stable_digest(tmp_path: Path) -> None:
    """Hashing should be stable for the same file content."""
    file_path = tmp_path / "invoice.pdf"
    file_path.write_text("same-content", encoding="utf-8")

    digest_a = compute_file_hash(file_path, "sha256")
    digest_b = compute_file_hash(file_path, "sha256")

    assert digest_a == digest_b
    assert len(digest_a) == 64
