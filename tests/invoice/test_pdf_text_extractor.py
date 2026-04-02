"""Tests for PDF text extraction behavior."""

from __future__ import annotations

from pathlib import Path

from invoice.ocr_provider import NullOcrProvider
from invoice.pdf_text_extractor import PdfTextExtractor


class _FakePage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _FakeReader:
    def __init__(self, _: str) -> None:
        self.pages = [_FakePage("发票号码 123456"), _FakePage("价税合计 88.00")]


def test_pdf_text_extractor_returns_text_when_reader_available(tmp_path: Path) -> None:
    """PDF extraction should join extracted page text."""
    pdf_path = tmp_path / "invoice.pdf"
    pdf_path.write_text("fake-pdf", encoding="utf-8")
    extractor = PdfTextExtractor(reader_factory=_FakeReader)

    result = extractor.extract_text(pdf_path)

    assert result.success is True
    assert "发票号码 123456" in result.text
    assert "价税合计 88.00" in result.text


def test_pdf_text_extractor_handles_missing_dependency_gracefully(
    tmp_path: Path,
) -> None:
    """The extractor should not crash when the PDF dependency is unavailable."""
    pdf_path = tmp_path / "invoice.pdf"
    pdf_path.write_text("fake-pdf", encoding="utf-8")
    extractor = PdfTextExtractor(reader_factory=None)

    result = extractor.extract_text(pdf_path)

    assert result.success is False
    assert result.status == "dependency_missing"
    assert result.text == ""


def test_null_ocr_provider_reports_not_supported(tmp_path: Path) -> None:
    """The placeholder OCR provider should explicitly report unsupported OCR."""
    pdf_path = tmp_path / "scanned.pdf"
    pdf_path.write_text("fake-pdf", encoding="utf-8")

    result = NullOcrProvider().extract_text(pdf_path)

    assert result.success is False
    assert result.status == "ocr_not_supported"
