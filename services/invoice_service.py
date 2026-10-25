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
from invoice.doc_classifier import DOC_E_INVOICE, classify_pdf_text
from invoice.eligibility import evaluate_eligibility
from invoice.excel_exporter import InvoiceExcelExporter
from invoice.expense_categories import suggest_category
from invoice.invoice_service_helpers import modified_time_for
from invoice.ledger_exporter import MonthlyLedgerExporter
from invoice.metadata_store import InvoiceMetadataStore
from invoice.parser import InvoiceParser
from invoice.pdf_text_extractor import PdfTextExtractor
from invoice.scanner import InvoiceScanner
from mail.importer import load_source_sidecar
from models.invoice import ArchiveCandidate, InvoicePreviewItem, InvoiceRecord
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
        self.ledger_exporter = MonthlyLedgerExporter()
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
            # Document gate: only real e-invoices may proceed into the
            # formal archive pipeline. Statements, vouchers, itineraries
            # and image-only PDFs stay pending for manual review — the old
            # parser alone cannot be trusted to reject them (baseline:
            # 16/20 non-invoices were parsed "complete").
            record.doc_type = classify_pdf_text(extraction.text)
            self._attach_mail_source(record, path)
            self._apply_manual_overrides(record)
            if not record.expense_category:
                record.expense_category = suggest_category(record)
            duplicate_result = self.deduplicator.check(record)
            plan = self.archive_planner.plan(record, duplicate_result.status, config)

            is_skipped = False
            skip_reason = ""
            target_path = plan.target_path

            if record.doc_type != DOC_E_INVOICE:
                is_skipped = True
                skip_reason = f"non_invoice:{record.doc_type}"
                target_path = ""
            elif duplicate_result.status == "待确认":
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
                    remark=(
                        f"文档类型: {record.doc_type}"
                        if record.doc_type != DOC_E_INVOICE
                        else duplicate_result.reason
                    ),
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
            # Execute-time gate: re-verify the document type instead of
            # trusting the preview flag alone, so a non-invoice can never
            # reach the ledger even if a preview row was built or
            # tampered with before classification ran.
            gated = (
                preview.record is not None
                and preview.record.doc_type
                and preview.record.doc_type != DOC_E_INVOICE
            )
            if preview.is_skipped or gated:
                skipped_count += 1
                task.items.append(
                    TaskItemRecord(
                        source_path=preview.source_path,
                        target_path=preview.target_path,
                        operation="skip",
                        item_type="invoice",
                        status="skipped",
                        error=(
                            f"non_invoice:{preview.record.doc_type}"
                            if gated and not preview.is_skipped
                            else preview.skip_reason
                        ),
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
                    preview.record.archive_status = "auto_archived"
                    preview.record.archived_at = datetime.now().isoformat(
                        timespec="seconds"
                    )
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
            self.export_monthly_ledger(month_key, config, metadata_records=metadata_records)

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

    # ------------------------------------------------------------------
    # S3.3 auto-archive admission, manual review, monthly ledger
    # ------------------------------------------------------------------

    _OVERRIDABLE_FIELDS = (
        "invoice_number", "invoice_date", "amount", "tax_amount",
        "buyer", "seller", "invoice_content", "expense_category",
        "reimburser", "expense_location", "reimburse_state",
    )
    _CARRIED_STATE_FIELDS = (
        "archive_status", "review_status", "expense_category",
        "reimburser", "expense_location", "reimburse_state", "archived_at",
    )

    def _apply_manual_overrides(self, record: InvoiceRecord) -> None:
        """Carry user-confirmed values and workflow state onto a rescan.

        A rescan must never silently replace values the reviewer already
        confirmed, so stored manual overrides win over re-parsed output.
        """
        if not record.file_hash:
            return
        stored = next(
            (
                r
                for r in self.metadata_store.load_records()
                if r.file_hash == record.file_hash
            ),
            None,
        )
        if stored is None:
            return
        for name in self._OVERRIDABLE_FIELDS:
            if name in stored.manual_overrides:
                setattr(record, name, stored.manual_overrides[name])
        for name in self._CARRIED_STATE_FIELDS:
            value = getattr(stored, name, None)
            if value and name not in stored.manual_overrides:
                setattr(record, name, value)

    def evaluate_pending(
        self,
        config: InvoiceConfig,
        cancel_event: threading.Event | None = None,
    ) -> list[ArchiveCandidate]:
        """Dry-run evaluation: classify, dedup, hash-verify, eligibility.

        Pure read operation — nothing is moved or persisted.
        """
        candidates: list[ArchiveCandidate] = []
        for path in self.scan_pending(config, cancel_event=cancel_event):
            raise_if_cancelled(cancel_event)
            extraction = self.pdf_extractor.extract_text(path)
            file_hash = compute_file_hash(path, config.hash_algorithm)
            record = self.parser.parse(
                file_path=path,
                extracted_text=extraction.text,
                file_hash=file_hash,
                modified_at=modified_time_for(path),
            )
            record.doc_type = classify_pdf_text(extraction.text)
            self._attach_mail_source(record, path)
            self._apply_manual_overrides(record)
            if not record.expense_category:
                record.expense_category = suggest_category(record)
            duplicate_result = self.deduplicator.check(record)
            # Re-read bytes to prove the PDF is still readable and its
            # SHA-256 matches what we fingerprinted moments ago.
            hash_ok = compute_file_hash(path, config.hash_algorithm) == file_hash
            verdict = evaluate_eligibility(record, duplicate_result.status, hash_ok)
            candidates.append(
                ArchiveCandidate(
                    record=record,
                    source_path=str(path),
                    duplicate_status=duplicate_result.status,
                    duplicate_reason=duplicate_result.reason,
                    eligible=verdict.eligible,
                    reasons=verdict.reasons,
                )
            )
        return candidates

    def _upsert_record(self, record: InvoiceRecord) -> list[InvoiceRecord]:
        records = self.metadata_store.load_records()
        for idx, existing in enumerate(records):
            if existing.file_hash and existing.file_hash == record.file_hash:
                records[idx] = record
                return records
        records.append(record)
        return records

    def save_manual_review(self, record: InvoiceRecord, updates: dict) -> None:
        """Persist reviewer edits; rescan will not overwrite them."""
        clean = {k: v for k, v in updates.items() if k in self._OVERRIDABLE_FIELDS}
        for name, value in clean.items():
            setattr(record, name, value)
        record.manual_overrides.update(clean)
        self.metadata_store.save_records(self._upsert_record(record))

    def set_review_state(self, record: InvoiceRecord, state: str) -> None:
        """Mark a record confirmed (ready to archive) or deferred."""
        record.review_status = state
        if state == "pending_review":
            record.archive_status = "deferred"
        self.metadata_store.save_records(self._upsert_record(record))

    def _move_to_archive(
        self, record: InvoiceRecord, source: Path, config: InvoiceConfig
    ) -> Path:
        plan = self.archive_planner.plan(record, "新发票", config)
        target = resolve_conflict_path(Path(plan.target_path))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        source_sidecar = Path(str(source) + ".source.json")
        if source_sidecar.exists():
            shutil.move(str(source_sidecar), str(target) + ".source.json")
        record.file_path = str(target)
        record.archived_at = datetime.now().isoformat(timespec="seconds")
        return target

    def archive_confirmed(
        self,
        record: InvoiceRecord,
        config: InvoiceConfig,
        status: str = "manually_archived",
    ) -> Path:
        """Move a confirmed record into the archive with backend re-checks.

        Re-verifies hash, doc type, eligibility and duplicates so the
        archive can never be reached through a stale or tampered row.
        """
        source = Path(record.file_path)
        file_hash = compute_file_hash(source, config.hash_algorithm)
        if record.file_hash and file_hash != record.file_hash:
            raise ValueError("文件哈希与登记值不一致，拒绝归档")
        record.file_hash = file_hash
        extraction = self.pdf_extractor.extract_text(source)
        record.doc_type = classify_pdf_text(extraction.text)
        duplicate_result = self.deduplicator.check(record)
        # Absolute blocks only — doc type and unreadable files. Reviewer
        # overrides may legitimately clear field-level data issues, so
        # weak-evidence verdicts are not re-applied here.
        if record.doc_type != DOC_E_INVOICE:
            raise ValueError(f"非电子发票({record.doc_type})，拒绝归档")
        if duplicate_result.status == "强重复":
            raise ValueError(f"强重复({duplicate_result.reason})，拒绝归档")
        target = self._move_to_archive(record, source, config)
        record.archive_status = status
        record.review_status = "confirmed"
        records = self._upsert_record(record)
        self.metadata_store.save_records(records)
        month_key = plan_month(record.invoice_date)
        self.export_monthly_ledger(month_key, config, metadata_records=records)
        return target

    def auto_archive(
        self,
        config: InvoiceConfig,
        dry_run: bool = True,
        cancel_event: threading.Event | None = None,
    ) -> list[ArchiveCandidate]:
        """Evaluate pending files; move eligible ones when not dry-run.

        Eligibility is a hard-condition gate — ``complete`` alone is
        never sufficient.  Non-eligible items stay in pending and appear
        in the review queue with reason codes.
        """
        candidates = self.evaluate_pending(config, cancel_event=cancel_event)
        if dry_run:
            return candidates
        for candidate in candidates:
            raise_if_cancelled(cancel_event)
            if not candidate.eligible:
                continue
            record = candidate.record
            self._move_to_archive(record, Path(candidate.source_path), config)
            record.archive_status = "auto_archived"
            records = self._upsert_record(record)
            self.metadata_store.save_records(records)
            month_key = plan_month(record.invoice_date)
            self.export_monthly_ledger(month_key, config, metadata_records=records)
        # File identified non-invoices away automatically so pending
        # only keeps items needing human attention.
        self.archive_non_invoices(candidates, config, cancel_event)
        return candidates

    def export_monthly_ledger(
        self,
        month_key: str,
        config: InvoiceConfig,
        reimburser_default: str = "",
        metadata_records: list[InvoiceRecord] | None = None,
    ) -> Path:
        """Regenerate the two-sheet monthly ledger from archived records.

        Pure regeneration — repeated exports can never duplicate rows or
        double-count amounts.
        """
        records = metadata_records if metadata_records is not None else self.metadata_store.load_records()
        monthly = [
            r
            for r in records
            if (r.archive_status in ("auto_archived", "manually_archived"))
            and plan_month(r.invoice_date) == month_key
        ]
        report_dir = Path(config.root_dir) / config.report_dir_name
        path = report_dir / f"月度台账_{month_key}.xlsx"
        return self.ledger_exporter.export(path, monthly, reimburser_default)

    def archived_months(self) -> list[str]:
        months = {
            plan_month(r.invoice_date)
            for r in self.metadata_store.load_records()
            if r.invoice_date and r.archive_status
        }
        return sorted(months, reverse=True)

    _OTHER_VOUCHER_TYPES = {"travel_voucher", "hotel_folio", "other_pdf"}
    _UNIDENTIFIED_TYPES = {"needs_ocr", "unknown"}

    def review_summary(self, candidates: list[ArchiveCandidate]) -> dict:
        """Split non-eligible items into meaningful buckets.

        Only e_invoice records with field-level problems need human
        review; recognized non-invoices are either other vouchers
        (already identifiable) or unidentified files (OCR/unknown).
        """
        eligible = sum(1 for c in candidates if c.eligible)
        return {
            "eligible": eligible,
            "needs_review": sum(
                1
                for c in candidates
                if not c.eligible and c.record.doc_type == DOC_E_INVOICE
            ),
            "other_voucher": sum(
                1
                for c in candidates
                if c.record.doc_type in self._OTHER_VOUCHER_TYPES
            ),
            "unidentified": sum(
                1
                for c in candidates
                if c.record.doc_type in self._UNIDENTIFIED_TYPES
            ),
        }


    _NON_INVOICE_MOVABLE_TYPES = {
        "travel_voucher", "hotel_folio", "other_pdf", "unknown",
    }

    def archive_non_invoices(
        self,
        candidates: list[ArchiveCandidate],
        config: InvoiceConfig,
        cancel_event: threading.Event | None = None,
    ) -> dict:
        """Move identified non-invoice PDFs out of pending into the
        review/non-invoice attachment directory.

        ``needs_ocr`` files stay pending — they still need OCR/manual
        handling.  Name conflicts are resolved by content: an identical
        (same-hash) file already in the review dir means the pending
        copy is redundant and is removed; a different file with the
        same name gets a numeric suffix.  ``.source.json`` sidecars
        move with their PDF.  Returns per-file results.
        """
        review_dir = Path(config.root_dir) / "待审核附件"
        review_dir.mkdir(parents=True, exist_ok=True)
        moved: list[str] = []
        merged: list[str] = []
        kept: list[str] = []

        for candidate in candidates:
            raise_if_cancelled(cancel_event)
            record = candidate.record
            if record.doc_type not in self._NON_INVOICE_MOVABLE_TYPES:
                kept.append(candidate.source_path)
                continue
            source = Path(candidate.source_path)
            target = review_dir / source.name
            if target.exists():
                same = (
                    target.stat().st_size == source.stat().st_size
                    and compute_file_hash(target, config.hash_algorithm)
                    == compute_file_hash(source, config.hash_algorithm)
                )
                if same:
                    source.unlink()
                    Path(str(source) + ".source.json").unlink(missing_ok=True)
                    merged.append(str(target))
                    continue
                for idx in range(1, 1000):
                    alt = review_dir / f"{source.stem}_{idx}{source.suffix}"
                    if not alt.exists():
                        target = alt
                        break
            shutil.move(str(source), str(target))
            sidecar = Path(str(source) + ".source.json")
            if sidecar.exists():
                shutil.move(str(sidecar), str(target) + ".source.json")
            moved.append(str(target))

        return {"moved": moved, "merged": merged, "kept": kept}


def plan_month(invoice_date: str) -> str:
    """``YYYY-MM-DD`` -> ``YYYYMM`` (empty for missing/invalid dates)."""
    try:
        parts = invoice_date.split("-")
        if len(parts) == 3 and len(parts[0]) == 4:
            return parts[0] + parts[1]
    except (AttributeError, IndexError):
        pass
    return ""

