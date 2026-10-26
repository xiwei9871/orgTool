"""Read-only UNSEEN-mail invoice audit.

Freezes the exact ``UID SEARCH UNSEEN`` result, scans only those messages
with ``BODY.PEEK`` (never marks mail read), downloads PDF attachments with
transfer-decoding and dedup, classifies each PDF by document type, routes
high-confidence e-invoices into the pending invoice directory and every
other PDF into a review directory, and records source metadata so every
file traces back to (uid, part_number).

Server-side state is never mutated: SELECT is readonly, all fetches use
PEEK, and the final UNSEEN set is re-verified against the frozen one.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from invoice.doc_classifier import (
    DOC_E_INVOICE,
    DOC_NEEDS_OCR,
    classify_pdf_text,
    find_invoice_links,
)
from mail.attachment import (
    decode_transfer_body,
    extract_attachments,
    is_pdf_candidate,
    looks_like_pdf_bytes,
)
from mail.errors import MailErrorCode, MailSyncError
from mail.filenames import safe_join, sanitize_filename
from mail.importer import (
    atomic_write_bytes,
    build_raw_dir,
    build_source_info,
    month_key_from_date,
    sha256_bytes,
    write_source_sidecar,
)
from mail.imap_client import ImapClient
from mail.models import MailAccountConfig, MessageInfo
from mail import store as store_mod
from mail.store import MailSyncStore
from mail.sync_engine import MAX_MESSAGE_BYTES, _parse_message_info

logger = logging.getLogger(__name__)

DEFAULT_REVIEW_DIR = "非发票附件"


@dataclass
class PdfOutcome:
    uid: int
    part_number: str
    name: str
    action: str = ""  # downloaded | skipped_duplicate | failed
    doc_type: str = ""
    local_path: str = ""
    routed_to: str = ""  # pending | review | ""
    error: str = ""


@dataclass
class UnseenAuditResult:
    unseen_frozen: int = 0
    scanned: int = 0
    msgs_with_pdf: int = 0
    pdf_parts: int = 0
    dedup_skipped: int = 0
    downloaded: int = 0
    classified: dict = field(default_factory=dict)
    pending_copies: int = 0
    review_copies: int = 0
    link_candidates: list = field(default_factory=list)
    failures: list = field(default_factory=list)
    unseen_after: int = 0
    unseen_same: bool = True
    unseen_added: list = field(default_factory=list)
    unseen_removed: list = field(default_factory=list)
    outcomes: list = field(default_factory=list)


class UnseenAuditRunner:
    """One-shot, read-only audit of currently-unseen INBOX messages."""

    def __init__(
        self,
        client: ImapClient,
        store: MailSyncStore,
        account: MailAccountConfig,
        invoice_root: Path,
        raw_dir_name: str,
        pending_dir_name: str,
        review_dir_name: str = DEFAULT_REVIEW_DIR,
        text_extractor=None,
    ) -> None:
        self.client = client
        self.store = store
        self.account = account
        self.invoice_root = Path(invoice_root)
        self.raw_dir_name = raw_dir_name
        self.pending_dir_name = pending_dir_name
        self.review_dir_name = review_dir_name
        self._extract_text = text_extractor or _default_text_extractor

    def run(self, folder_name: str = "INBOX") -> UnseenAuditResult:
        result = UnseenAuditResult()
        sel = self.client.select_folder(folder_name)  # readonly
        folder = self.store.upsert_folder(self.account.account_id, folder_name)
        if not folder.uidvalidity:
            self.store.update_folder_state(folder.id, uidvalidity=sel.uidvalidity)
            folder = self.store.get_folder_by_id(folder.id)

        frozen = set(self.client.uid_search(unseen=True))
        result.unseen_frozen = len(frozen)
        for uid in sorted(frozen):
            self._process_message(uid, folder, result)

        after = set(self.client.uid_search(unseen=True))
        result.unseen_after = len(after)
        result.unseen_same = after == frozen
        result.unseen_added = sorted(after - frozen)
        result.unseen_removed = sorted(frozen - after)
        return result

    # ------------------------------------------------------------------

    def _process_message(self, uid: int, folder, result: UnseenAuditResult) -> None:
        result.scanned += 1
        try:
            header = self.client.fetch_header(uid)
            message = _parse_message_info(uid, header)
            tree = self.client.fetch_bodystructure(uid)
        except MailSyncError as exc:
            result.failures.append(
                {"uid": uid, "stage": "headers", "code": exc.code, "error": exc.message}
            )
            return
        parts = [p for p in extract_attachments(tree) if is_pdf_candidate(p)]
        if not parts:
            self._check_invoice_links(uid, message, result)
            return
        result.msgs_with_pdf += 1
        result.pdf_parts += len(parts)
        for part in parts:
            self._handle_part(uid, folder, message, part, result)

    def _handle_part(self, uid, folder, message, part, result) -> None:
        outcome = PdfOutcome(
            uid=uid, part_number=part.part_number, name=part.filename or ""
        )
        result.outcomes.append(outcome)
        record = self.store.upsert_attachment(
            account_id=self.account.account_id,
            folder_id=folder.id,
            uidvalidity=folder.uidvalidity,
            uid=uid,
            message_id=message.message_id,
            subject=message.subject,
            sender=message.sender,
            message_date=message.date,
            attachment_index=part.index,
            attachment_name=part.filename,
            part_number=part.part_number,
            size=part.size,
        )
        existing_path = Path(record.local_path) if record.local_path else None
        if (
            record.download_status == store_mod.STATUS_DONE
            and existing_path is not None
            and existing_path.exists()
        ):
            outcome.action = "skipped_duplicate"
            result.dedup_skipped += 1
            outcome.local_path = str(existing_path)
            self._classify_and_route(existing_path, message, part, result, outcome)
            return

        self.store.mark_attachment(record.id, store_mod.STATUS_DOWNLOADING)
        try:
            data = self.client.fetch_part(uid, part.part_number)
            data = decode_transfer_body(data, part.encoding or "")
        except MailSyncError as exc:
            self._fail(record.id, outcome, result, exc.code, exc.message)
            return
        if len(data) > MAX_MESSAGE_BYTES or (
            is_pdf_candidate(part) and not looks_like_pdf_bytes(data)
        ):
            code = (
                "附件超过资源上限" if len(data) > MAX_MESSAGE_BYTES else "附件内容不是有效 PDF"
            )
            self._fail(
                record.id, outcome, result, MailErrorCode.INVALID_PDF, code
            )
            return
        digest = sha256_bytes(data)
        dup = self.store.find_by_hash(digest, exclude_id=record.id)
        if dup is not None and dup.local_path and Path(dup.local_path).exists():
            self.store.mark_attachment(
                record.id,
                store_mod.STATUS_SKIPPED_DUPLICATE,
                local_path=dup.local_path,
                content_hash=digest,
            )
            outcome.action = "skipped_duplicate"
            result.dedup_skipped += 1
            outcome.local_path = dup.local_path
            self._classify_and_route(Path(dup.local_path), message, part, result, outcome)
            return

        month_key = month_key_from_date(message.date)
        raw_dir = build_raw_dir(
            self.invoice_root,
            self.raw_dir_name,
            self.account.label or self.account.email,
            month_key,
        )
        display = part.filename or f"附件-{uid}-{part.index}.pdf"
        if not display.casefold().endswith(".pdf"):
            display += ".pdf"
        safe_name = sanitize_filename(f"u{uid}_a{part.index}_{display}")
        try:
            target = atomic_write_bytes(safe_join(raw_dir, safe_name), data)
        except MailSyncError as exc:
            self._fail(record.id, outcome, result, exc.code, exc.message)
            return
        self.store.mark_attachment(
            record.id,
            store_mod.STATUS_DONE,
            local_path=str(target),
            content_hash=digest,
        )
        outcome.action = "downloaded"
        outcome.local_path = str(target)
        result.downloaded += 1
        self._classify_and_route(target, message, part, result, outcome)

    def _classify_and_route(self, path, message, part, result, outcome) -> None:
        text = self._extract_text(path)
        doc_type = classify_pdf_text(text)
        outcome.doc_type = doc_type
        result.classified[doc_type] = result.classified.get(doc_type, 0) + 1
        if doc_type == DOC_NEEDS_OCR:
            dest_dir = self.review_dir_name
        elif doc_type == DOC_E_INVOICE:
            dest_dir = self.pending_dir_name
        else:
            dest_dir = self.review_dir_name
        dest_root = safe_join(self.invoice_root, dest_dir)
        dest_root.mkdir(parents=True, exist_ok=True)
        display = part.filename or path.name
        if not display.casefold().endswith(".pdf"):
            display += ".pdf"
        # Route under the attachment display name so a re-run hits the same
        # filename the normal sync import produced (content-hash early exit),
        # instead of duplicating under the raw u<uid>_a0_ name.
        dest = dest_root / sanitize_filename(display)
        if dest.exists():
            # Never overwrite: same file already routed, or a different file
            # with the same display name gets a suffixed name instead.
            if sha256_bytes(dest.read_bytes()) == sha256_bytes(path.read_bytes()):
                outcome.routed_to = "pending" if dest_dir == self.pending_dir_name else "review"
                return
            stem, suffix = dest.stem, dest.suffix
            n = 2
            while (dest_root / f"{stem}-{n}{suffix}").exists():
                n += 1
            dest = dest_root / f"{stem}-{n}{suffix}"
        try:
            atomic_write_bytes(dest, path.read_bytes())
        except MailSyncError as exc:
            result.failures.append(
                {"uid": outcome.uid, "stage": "route", "code": exc.code, "error": exc.message}
            )
            return
        write_source_sidecar(
            dest,
            build_source_info(
                account_label=self.account.label or self.account.email,
                account_email=self.account.email,
                folder_name="INBOX",
                uid=outcome.uid,
                message=message,
                attachment_name=part.filename or dest.name,
                sha256=sha256_bytes(path.read_bytes()),
                downloaded_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            ),
        )
        outcome.routed_to = "pending" if dest_dir == self.pending_dir_name else "review"
        if outcome.routed_to == "pending":
            result.pending_copies += 1
        else:
            result.review_copies += 1

    def _check_invoice_links(self, uid, message: MessageInfo, result) -> None:
        try:
            raw = self.client.fetch_full_message(uid)
        except MailSyncError:
            return
        links = find_invoice_links(raw.decode("utf-8", errors="replace"))
        if links:
            result.link_candidates.append(
                {"uid": uid, "subject": message.subject, "links": links}
            )

    def _fail(self, record_id, outcome, result, code, message) -> None:
        self.store.mark_attachment(
            record_id,
            store_mod.STATUS_FAILED,
            last_error=str(message),
            last_error_code=code,
            increment_attempts=True,
        )
        outcome.action = "failed"
        outcome.error = str(message)
        result.failures.append(
            {"uid": outcome.uid, "stage": "download", "code": code, "error": str(message)}
        )


def _default_text_extractor(path: Path) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:  # noqa: BLE001
        return ""
