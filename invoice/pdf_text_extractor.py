"""PDF text extraction with graceful dependency fallback."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from models.invoice import TextExtractionResult

ReaderFactory = Callable[[str], Any]
_UNSET = object()


class PdfTextExtractor:
    """Extract text from PDF files using an injectable reader factory."""

    def __init__(self, reader_factory: ReaderFactory | None | object = _UNSET) -> None:
        self.reader_factory = (
            _load_pypdf_reader() if reader_factory is _UNSET else reader_factory
        )

    def extract_text(self, pdf_path: Path) -> TextExtractionResult:
        """Extract text from a PDF file without crashing on dependency issues."""
        if self.reader_factory is None:
            return TextExtractionResult(
                success=False,
                text="",
                status="dependency_missing",
                message="pypdf is not installed",
            )

        try:
            reader = self.reader_factory(str(pdf_path))
            parts = [page.extract_text() or "" for page in reader.pages]
            return TextExtractionResult(
                success=True,
                text="\n".join(part for part in parts if part),
                status="ok",
            )
        except Exception as exc:  # noqa: BLE001
            return TextExtractionResult(
                success=False,
                text="",
                status="extract_failed",
                message=str(exc),
            )


def _load_pypdf_reader() -> ReaderFactory | None:
    """Load the PdfReader lazily so the app can run without the dependency."""
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        return None
    return PdfReader
