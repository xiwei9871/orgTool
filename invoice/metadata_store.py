"""Persistence for invoice metadata used in deduplication."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from models.invoice import InvoiceRecord


class InvoiceMetadataStore:
    """Store and retrieve invoice metadata records as JSON."""

    def __init__(self, metadata_dir: Path) -> None:
        self.metadata_dir = metadata_dir
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.metadata_dir / "invoice_index.json"

    def load_records(self) -> list[InvoiceRecord]:
        """Load known invoice records from disk."""
        if not self.index_file.exists():
            return []
        data = json.loads(self.index_file.read_text(encoding="utf-8"))
        return [InvoiceRecord(**item) for item in data]

    def save_records(self, records: list[InvoiceRecord]) -> Path:
        """Persist invoice records to disk."""
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        self.index_file.write_text(
            json.dumps([asdict(record) for record in records], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return self.index_file
