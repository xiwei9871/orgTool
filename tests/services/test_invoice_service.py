"""Tests for the invoice workflow service."""

from __future__ import annotations

from pathlib import Path

from config.schema import InvoiceConfig
from invoice.pdf_text_extractor import PdfTextExtractor
from services.invoice_service import InvoiceService
from utils.paths import RuntimePaths


class _StaticReader:
    def __init__(self, path: str) -> None:
        name = Path(path).name
        if "partial" in name:
            self.pages = [_Page("")]
        else:
            self.pages = [
                _Page(
                    "\n".join(
                        [
                            "发票号码：12345678",
                            "开票日期：2026-03-05",
                            "发票内容：办公用品",
                            "价税合计：88.50",
                        ]
                    )
                )
            ]


class _Page:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


def test_invoice_service_processes_new_invoice_and_updates_outputs(
    tmp_path: Path,
) -> None:
    """The invoice service should scan, preview, archive, and export a report."""
    invoice_root = tmp_path / "invoice_root"
    pending_dir = invoice_root / "发票归档_待处理"
    pending_dir.mkdir(parents=True)
    (pending_dir / "京东发票.pdf").write_text("fake-pdf", encoding="utf-8")

    runtime_root = tmp_path / "runtime"
    paths = RuntimePaths(
        root=runtime_root,
        config_file=runtime_root / "config.json",
        logs_dir=runtime_root / "logs",
        tasks_dir=runtime_root / "tasks",
        invoice_metadata_dir=runtime_root / "invoice_metadata",
    )
    paths.ensure_dirs()

    service = InvoiceService(
        runtime_paths=paths,
        pdf_extractor=PdfTextExtractor(reader_factory=_StaticReader),
    )
    config = InvoiceConfig(root_dir=str(invoice_root))

    scanned = service.scan_pending(config)
    preview = service.build_preview(scanned, config)
    task = service.execute_preview(preview, config)

    assert len(scanned) == 1
    assert len(preview) == 1
    assert preview[0].duplicate_status == "新发票"
    assert task.status == "success"
    assert (invoice_root / "按月份归档" / "发票202603" / "京东发票.pdf").exists()
    assert (invoice_root / "导出报表" / "发票台账_202603.xlsx").exists()
    assert (paths.invoice_metadata_dir / "invoice_index.json").exists()


def test_invoice_service_skips_partial_recognition_items(tmp_path: Path) -> None:
    """Recognition-incomplete invoices should be held for review instead of moved."""
    invoice_root = tmp_path / "invoice_root"
    pending_dir = invoice_root / "发票归档_待处理"
    pending_dir.mkdir(parents=True)
    partial_pdf = pending_dir / "partial.pdf"
    partial_pdf.write_text("fake-pdf", encoding="utf-8")

    runtime_root = tmp_path / "runtime"
    paths = RuntimePaths(
        root=runtime_root,
        config_file=runtime_root / "config.json",
        logs_dir=runtime_root / "logs",
        tasks_dir=runtime_root / "tasks",
        invoice_metadata_dir=runtime_root / "invoice_metadata",
    )
    paths.ensure_dirs()

    service = InvoiceService(
        runtime_paths=paths,
        pdf_extractor=PdfTextExtractor(reader_factory=_StaticReader),
    )
    config = InvoiceConfig(root_dir=str(invoice_root))

    preview = service.build_preview(service.scan_pending(config), config)

    assert preview[0].is_skipped is True
    assert preview[0].duplicate_status == "待确认"
    assert partial_pdf.exists() is True


def test_document_gate_blocks_non_invoice_from_archive(tmp_path: Path) -> None:
    """Non-invoice PDFs must be skipped by the gate, never moved/archived."""
    invoice_root = tmp_path / "invoice_root"
    pending_dir = invoice_root / "发票归档_待处理"
    pending_dir.mkdir(parents=True)
    folio = pending_dir / "结账单.pdf"
    folio.write_text("fake-pdf", encoding="utf-8")

    class _FolioReader:
        def __init__(self, path: str) -> None:
            self.pages = [
                _Page(
                    "北京某酒店 结账单 入住日期：2026-09-14 离店日期：2026-09-16 "
                    "消费合计 763.30 付款合计 763.30 客人姓名 房间号 收银员"
                )
            ]

    runtime_root = tmp_path / "runtime"
    paths = RuntimePaths(
        root=runtime_root,
        config_file=runtime_root / "config.json",
        logs_dir=runtime_root / "logs",
        tasks_dir=runtime_root / "tasks",
        invoice_metadata_dir=runtime_root / "invoice_metadata",
    )
    paths.ensure_dirs()
    service = InvoiceService(
        runtime_paths=paths,
        pdf_extractor=PdfTextExtractor(reader_factory=_FolioReader),
    )
    config = InvoiceConfig(root_dir=str(invoice_root))

    preview = service.build_preview(service.scan_pending(config), config)
    assert preview[0].is_skipped is True
    assert preview[0].skip_reason == "non_invoice:hotel_folio"
    assert preview[0].target_path == ""
    task = service.execute_preview(preview, config)
    assert task.summary["moved"] == 0
    assert folio.exists() is True
    # nothing landed in the monthly archive
    assert not (invoice_root / "按月份归档").exists()


def test_execute_preview_rechecks_document_gate(tmp_path: Path) -> None:
    """Execute-time must re-verify doc_type even when is_skipped was cleared."""
    from models.invoice import InvoicePreviewItem, InvoiceRecord

    invoice_root = tmp_path / "invoice_root"
    pending_dir = invoice_root / "发票归档_待处理"
    pending_dir.mkdir(parents=True)
    folio = pending_dir / "结账单.pdf"
    folio.write_text("fake-pdf", encoding="utf-8")

    runtime_root = tmp_path / "runtime"
    paths = RuntimePaths(
        root=runtime_root,
        config_file=runtime_root / "config.json",
        logs_dir=runtime_root / "logs",
        tasks_dir=runtime_root / "tasks",
        invoice_metadata_dir=runtime_root / "invoice_metadata",
    )
    paths.ensure_dirs()
    service = InvoiceService(runtime_paths=paths)
    config = InvoiceConfig(root_dir=str(invoice_root))

    record = InvoiceRecord(
        file_name="结账单.pdf",
        file_path=str(folio),
        file_hash="x",
        doc_type="hotel_folio",
    )
    # A stale/forged preview row: not skipped, has a target path.
    forged = InvoicePreviewItem(
        file_name="结账单.pdf",
        source_path=str(folio),
        invoice_number="X",
        invoice_date="2026-10-22",
        amount=763.30,
        content="",
        duplicate_status="新发票",
        target_path=str(invoice_root / "按月份归档" / "发票202610" / "结账单.pdf"),
        report_path="",
        month_key="202610",
        status="complete",
        remark="",
        is_skipped=False,
        skip_reason="",
        record=record,
    )
    task = service.execute_preview([forged], config)
    assert task.summary["moved"] == 0
    assert task.summary["skipped"] == 1
    assert task.items[0].error == "non_invoice:hotel_folio"
    assert folio.exists() is True
    assert not (invoice_root / "按月份归档").exists()
