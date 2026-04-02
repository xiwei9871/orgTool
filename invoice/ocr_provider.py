"""OCR provider abstraction for future scanned-invoice support."""

from __future__ import annotations

from pathlib import Path

from models.invoice import TextExtractionResult


class NullOcrProvider:
    """Placeholder OCR provider used in the MVP."""

    def extract_text(self, file_path: Path) -> TextExtractionResult:
        """Report that OCR is not implemented in the MVP."""
        return TextExtractionResult(
            success=False,
            text="",
            status="ocr_not_supported",
            message=f"OCR is not available for {file_path.name}",
        )
