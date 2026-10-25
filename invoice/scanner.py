"""Pending invoice file scanning."""

from __future__ import annotations

import threading
from pathlib import Path

from core.errors import raise_if_cancelled


class InvoiceScanner:
    """Scan the invoice pending directory for supported files."""

    def scan_pending_dir(
        self,
        pending_dir: Path,
        cancel_event: threading.Event | None = None,
    ) -> list[Path]:
        """Return top-level PDF files from the pending invoice directory."""
        results: list[Path] = []
        for path in pending_dir.iterdir():
            raise_if_cancelled(cancel_event)
            if path.is_file() and path.suffix.casefold() == ".pdf":
                results.append(path)
        return sorted(results, key=lambda path: path.name.casefold())
