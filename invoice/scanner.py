"""Pending invoice file scanning."""

from __future__ import annotations

from pathlib import Path


class InvoiceScanner:
    """Scan the invoice pending directory for supported files."""

    def scan_pending_dir(self, pending_dir: Path) -> list[Path]:
        """Return top-level PDF files from the pending invoice directory."""
        return sorted(
            [
                path
                for path in pending_dir.iterdir()
                if path.is_file() and path.suffix.casefold() == ".pdf"
            ],
            key=lambda path: path.name.casefold(),
        )
