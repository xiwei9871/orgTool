"""Invoice review dialog: PDF preview left, editable fields right (S3.3)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from invoice.eligibility import _REASON_TEXT
from invoice.expense_categories import DEFAULT_CATEGORY_RULES, PENDING_CATEGORY
from models.invoice import ArchiveCandidate, InvoiceRecord

_SOURCE_TEXT = {
    "label": "标签",
    "label_window": "标签窗口",
    "dzfp_block": "数电票区块",
    "filename_verified": "文件名核验",
    "daxie": "大写金额",
    "verified": "勾稽验证",
    "fallback": "兜底",
    "modified_time": "文件时间",
    "manual": "人工",
}


class PdfPreviewDialog(QDialog):
    """Read-only PDF viewer."""

    def __init__(self, pdf_path: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(Path(pdf_path).name)
        self.resize(760, 900)
        self.document = QPdfDocument(self)
        status = self.document.load(pdf_path)
        self.view = QPdfView(self)
        self.view.setDocument(self.document)
        layout = QVBoxLayout(self)
        if status == QPdfDocument.Status.Error:
            layout.addWidget(QLabel("无法读取该 PDF 文件。"))
        layout.addWidget(self.view)


class ReviewDialog(QDialog):
    """Edit recognized fields against the original PDF, then decide.

    ``self.action`` reports the chosen outcome after ``exec()``:
    ``"save"``, ``"archive"``, ``"defer"`` or ``None``.
    """

    def __init__(
        self,
        candidate: ArchiveCandidate,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.candidate = candidate
        self.record: InvoiceRecord = candidate.record
        self.action: str | None = None
        self.setWindowTitle(f"发票审核 — {Path(candidate.source_path).name}")
        self.resize(1100, 720)

        self.document = QPdfDocument(self)
        status = self.document.load(candidate.source_path)
        self.view = QPdfView(self)
        self.view.setDocument(self.document)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        if status == QPdfDocument.Status.Error:
            left_layout.addWidget(QLabel("无法读取该 PDF，请检查原件。"))
        left_layout.addWidget(self.view)

        right = self._build_form()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([640, 460])

        layout = QVBoxLayout(self)
        layout.addWidget(splitter)

    def _build_form(self) -> QWidget:
        record = self.record
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.number_edit = QLineEdit(record.invoice_number or "")
        self.date_edit = QLineEdit(record.invoice_date or "")
        self.date_edit.setPlaceholderText("YYYY-MM-DD")
        self.amount_edit = QLineEdit(
            "" if record.amount is None else f"{record.amount:.2f}"
        )
        self.tax_edit = QLineEdit(
            "" if record.tax_amount is None else f"{record.tax_amount:.2f}"
        )
        self.buyer_edit = QLineEdit(record.buyer or "")
        self.seller_edit = QLineEdit(record.seller or "")
        self.content_edit = QLineEdit(record.invoice_content or "")
        self.reimburser_edit = QLineEdit(record.reimburser or "")
        self.location_edit = QLineEdit(record.expense_location or "")

        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        categories = [PENDING_CATEGORY, *DEFAULT_CATEGORY_RULES.keys()]
        self.category_combo.addItems(categories)
        current = record.expense_category or PENDING_CATEGORY
        idx = self.category_combo.findText(current)
        self.category_combo.setCurrentIndex(idx if idx >= 0 else 0)
        if idx < 0:
            self.category_combo.setEditText(current)

        form = QFormLayout()
        form.addRow("发票号码", self.number_edit)
        form.addRow("开票日期", self.date_edit)
        form.addRow("价税合计", self.amount_edit)
        form.addRow("税额", self.tax_edit)
        form.addRow("购买方", self.buyer_edit)
        form.addRow("销售方", self.seller_edit)
        form.addRow("发票内容", self.content_edit)
        form.addRow("费用类别", self.category_combo)
        form.addRow("报销人", self.reimburser_edit)
        form.addRow("费用发生地", self.location_edit)
        layout.addLayout(form)

        sources = record.field_sources or {}
        evidence = " · ".join(
            f"{key}:{_SOURCE_TEXT.get(src, src)}" for key, src in sources.items()
        )
        self.evidence_label = QLabel(f"字段证据: {evidence or '无'}")
        self.evidence_label.setWordWrap(True)
        reason_texts = [
            _REASON_TEXT.get(r, r) for r in self.candidate.reasons
        ]
        header_bits = [f"类型: {record.doc_type}"]
        if record.review_fields:
            header_bits.append("待复核: " + "、".join(record.review_fields))
        if reason_texts:
            header_bits.append("拦阻原因: " + "、".join(reason_texts))
        header_bits.append(f"重复状态: {self.candidate.duplicate_status}")
        self.status_label = QLabel(" | ".join(header_bits))
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addWidget(self.evidence_label)

        button_row = QHBoxLayout()
        self.save_button = QPushButton("保存修改")
        self.archive_button = QPushButton("确认归档")
        self.defer_button = QPushButton("暂缓处理")
        self.close_button = QPushButton("关闭")
        button_row.addWidget(self.save_button)
        button_row.addWidget(self.archive_button)
        button_row.addWidget(self.defer_button)
        button_row.addStretch(1)
        button_row.addWidget(self.close_button)
        layout.addLayout(button_row)

        self.save_button.clicked.connect(lambda: self._finish("save"))
        self.archive_button.clicked.connect(lambda: self._finish("archive"))
        self.defer_button.clicked.connect(lambda: self._finish("defer"))
        self.close_button.clicked.connect(self.reject)
        return widget

    def _finish(self, action: str) -> None:
        self.action = action
        self.accept()

    def collect_updates(self) -> dict:
        """Return the edited fields for :meth:`save_manual_review`."""
        record = self.record

        def amount(text: str, fallback):
            text = text.strip()
            if not text:
                return None
            try:
                return round(float(text), 2)
            except ValueError:
                return fallback

        return {
            "invoice_number": self.number_edit.text().strip(),
            "invoice_date": self.date_edit.text().strip(),
            "amount": amount(self.amount_edit.text(), record.amount),
            "tax_amount": amount(self.tax_edit.text(), record.tax_amount),
            "buyer": self.buyer_edit.text().strip(),
            "seller": self.seller_edit.text().strip(),
            "invoice_content": self.content_edit.text().strip(),
            "expense_category": self.category_combo.currentText().strip(),
            "reimburser": self.reimburser_edit.text().strip(),
            "expense_location": self.location_edit.text().strip(),
        }
