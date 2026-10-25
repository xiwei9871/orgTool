"""Service orchestration for invoice intake, deduplication, and archiving."""

from __future__ import annotations

import shutil
import threading
from datetime import datetime
from pathlib import Path

from config.schema import InvoiceConfig
from core.conflict_resolver import resolve_conflict_path
from core.errors import raise_if_cancelled
from core.task_store import TaskStore
from invoice.archive_planner import InvoiceArchivePlanner
from invoice.deduplicator import InvoiceDeduplicator
from invoice.excel_exporter import InvoiceExcelExporter
from invoice.invoice_service_helpers import modified_time_for
from invoice.metadata_store import InvoiceMetadataStore
from invoice.parser import InvoiceParser
from invoice.pdf_text_extractor import PdfTextExtractor
from invoice.scanner import InvoiceScanner
from mail.importer import load_source_sidecar
from models.invoice import InvoicePreviewItem, InvoiceRecord
from models.task import TaskItemRecord, TaskRecord
from utils.file_hash import compute_file_hash
from utils.paths import RuntimePaths


class InvoiceService:
    """Coordinate invoice scanning, previewing, and archive execution."""

    def __init__(
        self,
        runtime_paths: RuntimePaths,
        pdf_extractor: PdfTextExtractor | None = None,
    ) -> None:
        self.runtime_paths = runtime_paths
        self.scanner = InvoiceScanner()
        self.pdf_extractor = pdf_extractor or PdfTextExtractor()
        self.parser = InvoiceParser()
        self.metadata_store = InvoiceMetadataStore(runtime_paths.invoice_metadata_dir)
        self.deduplicator = InvoiceDeduplicator(self.metadata_store)
        self.archive_planner = InvoiceArchivePlanner()
        self.excel_exporter = InvoiceExcelExporter()
        self.task_store = TaskStore(runtime_paths)

    def scan_pending(
        self,
        config: InvoiceConfig,
        cancel_event: threading.Event | None = None,
    ) -> list[Path]:
        """Return pending PDF invoices.

        Raises ``FileNotFoundError`` when the configured invoice root does
        not exist so the caller can surface a clear message instead of
        silently creating directories from a mistyped path.
        """
        root_dir = Path(config.root_dir.strip()) if config.root_dir.strip() else None
        if root_dir is None or not root_dir.exists():
            raise FileNotFoundError(f"发票主目录不存在: {config.root_dir or '(未配置)'}")
        pending_dir = root_dir / config.pending_dir_name
        pending_dir.mkdir(parents=True, exist_ok=True)
        return self.scanner.scan_pending_dir(pending_dir, cancel_event=cancel_event)

    def build_preview(
        self,
        pending_files: list[Path],
        config: InvoiceConfig,
        cancel_event: threading.Event | None = None,
    ) -> list[InvoicePreviewItem]:
        """Build preview rows for pending invoices."""
        preview_items: list[InvoicePreviewItem] = []

        for path in pending_files:
            raise_if_cancelled(cancel_event)
            extraction = self.pdf_extractor.extract_text(path)
            record = self.parser.parse(
                file_path=path,
                extracted_text=extraction.text,
                file_hash=compute_file_hash(path, config.hash_algorithm),
                modified_at=modified_time_for(path),
            )
            self._attach_mail_source(record, path)
            duplicate_result = self.deduplicator.check(record)
            plan = self.archive_planner.plan(record, duplicate_result.status, config)

            is_skipped = False
            skip_reason = ""
            target_path = plan.target_path

            if duplicate_result.status == "待确认":
                is_skipped = True
                skip_reason = "review_required"
                target_path = ""
            elif duplicate_result.status == "强重复" and not config.move_strong_duplicates:
                is_skipped = True
                skip_reason = "strong_duplicate"
                target_path = ""

            preview_items.append(
                InvoicePreviewItem(
                    file_name=record.file_name,
                    source_path=record.file_path,
                    invoice_number=record.invoice_number,
                    invoice_date=record.invoice_date,
                    amount=record.amount,
                    content=record.invoice_content,
                    duplicate_status=duplicate_result.status,
                    target_path=target_path,
                    report_path=plan.report_path,
                    month_key=plan.month_key,
                    status=record.recognition_status,
                    remark=duplicate_result.reason,
                    is_skipped=is_skipped,
                    skip_reason=skip_reason,
                    record=record,
                )
            )

        return preview_items

    def _attach_mail_source(self, record: InvoiceRecord, path: Path) -> None:
        """Attach mail provenance from a ``.source.json`` sidecar if present."""
        source = load_source_sidecar(path)
        if source is None:
            return
        record.source_type = "mail"
        record.notes.append(
            "邮箱:{account} 文件夹:{folder} UID:{uid} 主题:{subject} "
            "发件人:{sender} 收件时间:{date} 附件:{attachment} 下载:{downloaded}".format(
                account=source.get("account_email", ""),
                folder=source.get("folder", ""),
                uid=source.get("uid", ""),
                subject=source.get("subject", ""),
                sender=source.get("sender", ""),
                date=source.get("message_date", ""),
                attachment=source.get("attachment_name", ""),
                downloaded=source.get("downloaded_at", ""),
            )
        )

    def execute_preview(
        self,
        preview_items: list[InvoicePreviewItem],
        config: InvoiceConfig,
        cancel_event: threading.Event | None = None,
    ) -> TaskRecord:
        """Execute invoice archive moves, metadata updates, and report export."""
        created_at = datetime.now().isoformat(timespec="seconds")
        task = TaskRecord(
            task_id=f"invoice-process-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            task_type="invoice_process",
            created_at=created_at,
            status="success",
            items=[],
            summary={},
        )

        metadata_records = self.metadata_store.load_records()
        touched_months: set[str] = set()
        moved_count = 0
        skipped_count = 0
        error_count = 0

        for preview in preview_items:
            raise_if_cancelled(cancel_event)
            if preview.is_skipped:
                skipped_count += 1
                task.items.append(
                    TaskItemRecord(
                        source_path=preview.source_path,
                        target_path=preview.target_path,
                        operation="skip",
                        item_type="invoice",
                        status="skipped",
                        error=preview.skip_reason,
                        extra={"duplicate_status": preview.duplicate_status},
                    )
                )
                continue

            source = Path(preview.source_path)
            target = resolve_conflict_path(Path(preview.target_path))
            target.parent.mkdir(parents=True, exist_ok=True)

            try:
                shutil.move(str(source), str(target))
                source_sidecar = Path(str(source) + ".source.json")
                if source_sidecar.exists():
                    shutil.move(
                        str(source_sidecar), str(target) + ".source.json"
                    )
                moved_count += 1
                preview.record.file_path = str(target)
                task.items.append(
                    TaskItemRecord(
                        source_path=preview.source_path,
                        target_path=str(target),
                        operation="move",
                        item_type="invoice",
                        status="success",
                        error="",
                        extra={"duplicate_status": preview.duplicate_status},
                    )
                )

                if preview.duplicate_status == "新发票":
                    metadata_records.append(preview.record)
                    touched_months.add(preview.month_key)
            except OSError as exc:
                error_count += 1
                task.items.append(
                    TaskItemRecord(
                        source_path=preview.source_path,
                        target_path=str(target),
                        operation="move",
                        item_type="invoice",
                        status="error",
                        error=str(exc),
                        extra={"duplicate_status": preview.duplicate_status},
                    )
                )

        self.metadata_store.save_records(metadata_records)

        for month_key in touched_months:
            monthly_records = [
                record
                for record in metadata_records
                if record.invoice_date.startswith(f"{month_key[:4]}-{month_key[4:6]}")
            ]
            report_path = Path(config.root_dir) / config.report_dir_name / config.excel_name_pattern.format(
                yyyymm=month_key
            )
            self.excel_exporter.export(report_path, monthly_records)

        task.status = "success" if error_count == 0 else "partial_success"
        task.summary = {
            "moved": moved_count,
            "skipped": skipped_count,
            "errors": error_count,
        }
        self.task_store.save(task)
        return task
