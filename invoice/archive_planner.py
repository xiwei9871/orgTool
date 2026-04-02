"""Invoice archive path planning."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from config.schema import InvoiceConfig
from models.invoice import InvoiceRecord


@dataclass(slots=True)
class InvoiceArchivePlan:
    """Resolved archive and report paths for one invoice."""

    target_path: str
    report_path: str
    month_key: str


class InvoiceArchivePlanner:
    """Plan invoice destinations based on date and duplicate status."""

    def plan(
        self,
        record: InvoiceRecord,
        duplicate_status: str,
        config: InvoiceConfig,
    ) -> InvoiceArchivePlan:
        """Build the archive and report paths for an invoice."""
        root_dir = Path(config.root_dir)
        month_key = record.invoice_date[:7].replace("-", "")
        report_path = root_dir / config.report_dir_name / config.excel_name_pattern.format(
            yyyymm=month_key
        )

        if duplicate_status == "强重复" and config.move_strong_duplicates:
            target_path = root_dir / config.duplicate_dir_name / record.file_name
        else:
            month_dir = config.month_folder_pattern.format(yyyymm=month_key)
            target_path = (
                root_dir / config.monthly_dir_name / month_dir / record.file_name
            )

        return InvoiceArchivePlan(
            target_path=str(target_path),
            report_path=str(report_path),
            month_key=month_key,
        )
