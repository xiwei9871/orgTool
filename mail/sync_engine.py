"""Mail synchronization engine: backfill, incremental sync, resume, retry."""

from __future__ import annotations

import dataclasses
import email.parser
import email.policy
import email.utils
import logging
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from core.conflict_resolver import resolve_conflict_path
from core.errors import OperationCancelled, raise_if_cancelled
from mail.attachment import (
    extract_attachments,
    is_pdf_candidate,
    looks_like_pdf_bytes,
)
from mail.errors import MailErrorCode, MailSyncError
from mail.filters import attachment_matches, attachment_too_large, message_matches
from mail.importer import (
    atomic_write_bytes,
    build_raw_dir,
    build_source_info,
    mask_email,
    month_key_from_date,
    sha256_bytes,
    write_source_sidecar,
)
from mail.filenames import safe_join, sanitize_filename
from mail.imap_client import ImapClient
from mail.models import MailAccountConfig, MessageInfo, SyncStatusSnapshot
from mail import store as store_mod
from mail.store import MailSyncStore

logger = logging.getLogger(__name__)

MODE_BACKFILL = "backfill"
MODE_INCREMENTAL = "incremental"
MODE_RETRY = "retry"

MAX_MESSAGE_BYTES = 200 * 1024 * 1024  # per-message safety cap
RETRY_ATTEMPTS = 5
RETRY_BASE_SECONDS = 1.0
RETRY_MAX_SECONDS = 60.0
FAILED_RETRY_LIMIT = 3


@dataclass(slots=True)
class EngineOptions:
    """Tunable knobs for one sync run."""

    batch_size: int = 50
    connect_timeout: float = 30.0
    retry_attempts: int = RETRY_ATTEMPTS
    failed_retry_limit: int = FAILED_RETRY_LIMIT


class MailSyncEngine:
    """Downloads mail attachments with idempotent, resumable semantics."""

    def __init__(
        self,
        store: MailSyncStore,
        invoice_root: Path,
        pending_dir_name: str,
        raw_dir_name: str,
        cancel_event: threading.Event,
        pause_event: threading.Event | None = None,
        snapshot: SyncStatusSnapshot | None = None,
        client_factory: Callable[..., ImapClient] | None = None,
        options: EngineOptions | None = None,
        secret_getter: Callable[[str], str | None] | None = None,
    ) -> None:
        self.store = store
        self.invoice_root = Path(invoice_root)
        self.pending_dir_name = pending_dir_name
        self.raw_dir_name = raw_dir_name
        self.cancel_event = cancel_event
        self.pause_event = pause_event or threading.Event()
        self.snapshot = snapshot or SyncStatusSnapshot()
        self._client_factory = client_factory or ImapClient
        self.options = options or EngineOptions()
        self._secret_getter = secret_getter
        self._client: ImapClient | None = None
        self._account: MailAccountConfig | None = None
        self._selected_folder: str | None = None

    # ------------------------------------------------------------------
    # Public entry point

    def run(
        self,
        account: MailAccountConfig,
        mode: str,
        since: date | None = None,
        until: date | None = None,
    ) -> SyncStatusSnapshot:
        """Synchronize one account's configured folders."""
        self._account = account
        self.snapshot.running = True
        self.snapshot.paused = False
        self.snapshot.account_label = account.label or account.email
        self.snapshot.mode = mode
        self.snapshot.last_error = ""
        self.snapshot.last_error_code = ""
        try:
            self._connect()
            self.store.reset_downloading(account.account_id)
            folders = account.folders or ["INBOX"]
            for folder_name in folders:
                self._checkpoint()
                self.snapshot.folder_name = folder_name
                self._sync_folder(account, folder_name, mode, since, until)
            if mode == MODE_INCREMENTAL:
                self._retry_failed(account)
            self.snapshot.running = False
            self.snapshot.paused = False
            return self.snapshot
        except OperationCancelled:
            self.snapshot.running = False
            self.snapshot.paused = False
            raise
        except MailSyncError as exc:
            self.snapshot.running = False
            self.snapshot.paused = False
            self.snapshot.last_error = exc.message
            self.snapshot.last_error_code = exc.code
            raise
        finally:
            self._disconnect()

    # ------------------------------------------------------------------
    # Connection management

    def _connect(self) -> None:
        self._disconnect()
        account = self._account
        assert account is not None
        client = self._client_factory(
            account.host,
            account.port,
            account.use_ssl,
            self.options.connect_timeout,
        )
        client.connect()
        secret = self._get_secret(account)
        client.login(account.email, secret)
        client.send_id()
        self._client = client
        self._selected_folder = None

    def _disconnect(self) -> None:
        if self._client is not None:
            try:
                self._client.logout()
            except Exception:
                pass
            self._client = None
            self._selected_folder = None

    def _get_secret(self, account: MailAccountConfig) -> str:
        if self._secret_getter is not None:
            secret = self._secret_getter(account.account_id)
        else:
            secret = None
        if not secret:
            raise MailSyncError(
                MailErrorCode.AUTH_CODE_REQUIRED,
                f"账户 {account.email} 未配置授权码",
            )
        return secret

    def _reconnect(self) -> None:
        # _connect() resets _selected_folder — capture it first so the
        # folder is re-selected on the fresh connection.
        folder = self._selected_folder
        self._connect()
        if folder is not None:
            self._client.select_folder(folder)

    def _with_retry(self, description: str, fn):
        """Run ``fn`` with exponential backoff on transient failures."""
        attempt = 0
        delay = RETRY_BASE_SECONDS
        while True:
            self._checkpoint()
            try:
                return fn()
            except MailSyncError as exc:
                if exc.code != MailErrorCode.NETWORK_TIMEOUT:
                    raise
                attempt += 1
                if attempt >= self.options.retry_attempts:
                    raise MailSyncError(
                        MailErrorCode.NETWORK_TIMEOUT,
                        f"{description}重试 {attempt} 次后仍失败",
                        detail=str(exc),
                    ) from exc
                logger.warning(
                    "%s transient failure (attempt %s), retrying in %.1fs",
                    description,
                    attempt,
                    delay,
                )
                time.sleep(delay)
                delay = min(delay * 2, RETRY_MAX_SECONDS)
                self._reconnect()

    # ------------------------------------------------------------------
    # Folder sync

    def _sync_folder(
        self,
        account: MailAccountConfig,
        folder_name: str,
        mode: str,
        since: date | None,
        until: date | None,
    ) -> None:
        result = self._with_retry(
            f"打开文件夹 {folder_name}",
            lambda: self._client.select_folder(folder_name),
        )
        self._selected_folder = folder_name

        folder = self.store.upsert_folder(account.account_id, folder_name)
        if folder.uidvalidity and folder.uidvalidity != result.uidvalidity:
            # UIDVALIDITY rollover: previously seen UIDs are meaningless.
            logger.warning(
                "UIDVALIDITY changed for %s (%s -> %s); rescanning folder",
                folder_name,
                folder.uidvalidity,
                result.uidvalidity,
            )
            folder = dataclasses.replace(
                folder, uidvalidity=result.uidvalidity, last_seen_uid=0
            )
        self.store.update_folder_state(folder.id, uidvalidity=result.uidvalidity)

        if mode == MODE_BACKFILL:
            self._backfill_folder(account, folder, result, since, until)
        else:
            self._incremental_folder(account, folder, result)

    def _backfill_folder(
        self,
        account: MailAccountConfig,
        folder,
        select_result,
        since: date | None,
        until: date | None,
    ) -> None:
        task = self._resume_or_create_backfill_task(
            account, folder, since, until
        )
        # Records left pending by a crash/interruption are drained first —
        # the cursor only tracks which UIDs still need scanning.
        self._drain_pending(account, folder, task["id"])
        cursor = int(task.get("cursor_uid") or 0)
        uids = self._with_retry(
            "搜索历史邮件",
            lambda: self._client.uid_search(
                since=since, before=until, uid_min=cursor + 1 if cursor else None
            ),
        )
        self.store.update_task(task["id"], total=len(uids))
        self.snapshot.total += len(uids)

        if select_result.exists > 0 and not uids and since is None and until is None:
            # The folder claims messages but search returns none: NetEase can
            # cap the history window exposed to clients. Surface as a hint,
            # not a hard error (may also be a server-side listing quirk).
            self.snapshot.last_error_code = MailErrorCode.SERVER_HISTORY_LIMIT
            self.snapshot.last_error = "服务器可能限制了历史邮件可见范围"

        for batch_start in range(0, len(uids), self.options.batch_size):
            batch = uids[batch_start : batch_start + self.options.batch_size]
            for uid in batch:
                self._checkpoint()
                try:
                    self._process_message(account, folder, uid, task["id"])
                except OperationCancelled:
                    self.store.update_task(task["id"], status=store_mod.TASK_CANCELLED)
                    raise
                except MailSyncError as exc:
                    if exc.code == MailErrorCode.NETWORK_TIMEOUT:
                        raise
                    logger.warning("uid %s failed: %s", uid, exc)
            self.store.update_task(task["id"], cursor_uid=batch[-1])
            self.store.update_folder_state(folder.id, last_seen_uid=max(folder.last_seen_uid, batch[-1]))
        self.store.update_task(task["id"], status=store_mod.TASK_DONE)

    def _resume_or_create_backfill_task(
        self,
        account: MailAccountConfig,
        folder,
        since: date | None,
        until: date | None,
    ) -> dict:
        unfinished = [
            t
            for t in self.store.unfinished_tasks(account.account_id)
            if t["folder_id"] == folder.id and t["mode"] == MODE_BACKFILL
        ]
        since_text = since.isoformat() if since else ""
        until_text = until.isoformat() if until else ""
        for task in unfinished:
            if (task.get("since_date") or "") == since_text and (
                task.get("until_date") or ""
            ) == until_text:
                self.store.update_task(task["id"], status=store_mod.TASK_RUNNING)
                return task
        task_id = self.store.create_task(
            account.account_id,
            folder.id,
            folder.name,
            MODE_BACKFILL,
            since_date=since_text,
            until_date=until_text,
        )
        return self.store.get_task(task_id)

    def _incremental_folder(self, account: MailAccountConfig, folder, select_result) -> None:
        task_id = self.store.create_task(
            account.account_id, folder.id, folder.name, MODE_INCREMENTAL
        )
        try:
            self._drain_pending(account, folder, task_id)
            uids = self._with_retry(
                "搜索新邮件",
                lambda: self._client.uid_search(uid_min=folder.last_seen_uid + 1),
            )
            self.store.update_task(task_id, total=len(uids))
            self.snapshot.total += len(uids)
            max_uid = folder.last_seen_uid
            for uid in uids:
                self._checkpoint()
                try:
                    self._process_message(account, folder, uid, task_id)
                except OperationCancelled:
                    self.store.update_task(task_id, status=store_mod.TASK_CANCELLED)
                    raise
                except MailSyncError as exc:
                    if exc.code == MailErrorCode.NETWORK_TIMEOUT:
                        raise
                    logger.warning("uid %s failed: %s", uid, exc)
                max_uid = max(max_uid, uid)
            self.store.update_folder_state(folder.id, last_seen_uid=max_uid)
            self.store.update_task(task_id, status=store_mod.TASK_DONE)
        except Exception:
            self.store.update_task(task_id, status=store_mod.TASK_FAILED)
            raise

    # ------------------------------------------------------------------
    # Message / attachment processing

    def _drain_pending(
        self, account: MailAccountConfig, folder, task_id: int
    ) -> None:
        """Re-attempt attachment records left pending by a previous run.

        A crash can happen after an attachment record was created but before
        its download finished (``pending``) or mid-download (``downloading``
        — reset to ``pending`` at run start). These records carry the UID and
        part number needed to resume the download without rescanning headers.
        """
        folder_state = self.store.get_folder_by_id(folder.id)
        if folder_state is None:
            return
        pending = self.store.pending_for_folder(
            account.account_id, folder.id, folder_state.uidvalidity
        )
        for record in pending:
            self._checkpoint()
            if self._selected_folder != folder.name:
                self._with_retry(
                    f"重新打开文件夹 {folder.name}",
                    lambda name=folder.name: self._client.select_folder(name),
                )
                self._selected_folder = folder.name
            message = MessageInfo(
                uid=record.uid,
                message_id=record.message_id,
                subject=record.subject,
                sender=record.sender,
                date=record.message_date,
            )
            part = _part_from_record(record)
            self._download_candidate(account, folder, message, part, task_id)

    def _process_message(
        self,
        account: MailAccountConfig,
        folder,
        uid: int,
        task_id: int,
    ) -> None:
        header = self._with_retry(
            f"读取邮件头 {uid}", lambda: self._client.fetch_header(uid)
        )
        message = _parse_message_info(uid, header)
        if not message_matches(message, account.filters):
            self._bump_task(task_id, "processed")
            return
        bodystructure = self._with_retry(
            f"读取邮件结构 {uid}", lambda: self._client.fetch_bodystructure(uid)
        )
        parts = extract_attachments(bodystructure)
        candidates = [p for p in parts if attachment_matches(p, account.filters)]
        if candidates:
            self._bump_task(task_id, "found", len(candidates))
        for part in candidates:
            self._checkpoint()
            self._download_candidate(account, folder, message, part, task_id)
        self._bump_task(task_id, "processed")

    def _download_candidate(
        self,
        account: MailAccountConfig,
        folder,
        message: MessageInfo,
        part,
        task_id: int,
    ) -> None:
        folder_state = self.store.get_folder_by_id(folder.id)
        record = self.store.upsert_attachment(
            account_id=account.account_id,
            folder_id=folder.id,
            uidvalidity=folder_state.uidvalidity if folder_state else 0,
            uid=message.uid,
            message_id=message.message_id,
            subject=message.subject,
            sender=message.sender,
            message_date=message.date,
            attachment_index=part.index,
            attachment_name=part.filename,
            part_number=part.part_number,
            size=part.size,
        )
        # Entity-level dedup: already downloaded and file still present.
        if (
            record.download_status == store_mod.STATUS_DONE
            and record.local_path
            and Path(record.local_path).exists()
        ):
            self._bump_task(task_id, "skipped_duplicate")
            self.snapshot.skipped_duplicate += 1
            return
        if attachment_too_large(part, account.filters):
            self.store.mark_attachment(
                record.id,
                store_mod.STATUS_FAILED,
                last_error=f"附件超过大小上限 {account.filters.max_attachment_mb}MB",
                last_error_code=MailErrorCode.ATTACHMENT_DECODE_FAILED,
                increment_attempts=True,
            )
            self._bump_task(task_id, "failed")
            self.snapshot.failed += 1
            return

        self.store.mark_attachment(record.id, store_mod.STATUS_DOWNLOADING)
        try:
            data = self._with_retry(
                f"下载附件 {part.filename or part.part_number}",
                lambda: self._client.fetch_part(message.uid, part.part_number),
            )
        except MailSyncError as exc:
            status = (
                store_mod.STATUS_SERVER_UNAVAILABLE
                if exc.code == MailErrorCode.ATTACHMENT_DECODE_FAILED
                else store_mod.STATUS_FAILED
            )
            self.store.mark_attachment(
                record.id,
                status,
                last_error=exc.message,
                last_error_code=exc.code,
                increment_attempts=True,
            )
            self._bump_task(task_id, "failed")
            self.snapshot.failed += 1
            return

        if len(data) > MAX_MESSAGE_BYTES:
            self.store.mark_attachment(
                record.id,
                store_mod.STATUS_FAILED,
                last_error="附件超过资源上限",
                last_error_code=MailErrorCode.ATTACHMENT_DECODE_FAILED,
                increment_attempts=True,
            )
            self._bump_task(task_id, "failed")
            self.snapshot.failed += 1
            return

        want_pdf = is_pdf_candidate(part)
        if want_pdf and not looks_like_pdf_bytes(data):
            self.store.mark_attachment(
                record.id,
                store_mod.STATUS_FAILED,
                last_error="附件内容不是有效 PDF",
                last_error_code=MailErrorCode.INVALID_PDF,
                increment_attempts=True,
            )
            self._bump_task(task_id, "failed")
            self.snapshot.failed += 1
            return

        digest = sha256_bytes(data)
        duplicate = self.store.find_by_hash(digest, exclude_id=record.id)
        if duplicate is not None and duplicate.local_path and Path(duplicate.local_path).exists():
            self.store.mark_attachment(
                record.id,
                store_mod.STATUS_SKIPPED_DUPLICATE,
                local_path=duplicate.local_path,
                content_hash=digest,
            )
            self._bump_task(task_id, "skipped_duplicate")
            self.snapshot.skipped_duplicate += 1
            return

        month_key = month_key_from_date(message.date)
        raw_dir = build_raw_dir(
            self.invoice_root, self.raw_dir_name, account.label or account.email, month_key
        )
        display_name = part.filename or f"附件-{message.uid}-{part.index}.pdf"
        safe_name = sanitize_filename(f"u{message.uid}_a{part.index}_{display_name}")
        try:
            target = atomic_write_bytes(safe_join(raw_dir, safe_name), data)
        except MailSyncError as exc:
            self.store.mark_attachment(
                record.id,
                store_mod.STATUS_FAILED,
                last_error=exc.message,
                last_error_code=exc.code,
                increment_attempts=True,
            )
            self._bump_task(task_id, "failed")
            self.snapshot.failed += 1
            return

        self.store.mark_attachment(
            record.id,
            store_mod.STATUS_DONE,
            local_path=str(target),
            content_hash=digest,
        )
        self._bump_task(task_id, "downloaded")
        self.snapshot.downloaded += 1

        if account.import_to_pending and want_pdf:
            self._import_to_pending(account, folder, message, part, target, digest)

    def _import_to_pending(
        self,
        account: MailAccountConfig,
        folder,
        message: MessageInfo,
        part,
        raw_path: Path,
        digest: str,
    ) -> None:
        pending_dir = safe_join(self.invoice_root, self.pending_dir_name)
        pending_dir.mkdir(parents=True, exist_ok=True)
        display = part.filename or raw_path.name
        target = pending_dir / sanitize_filename(display)
        if target.exists():
            # Same-content file already pending → skip; different content
            # with the same name gets a conflict-resolved name instead of
            # being silently dropped or overwriting the existing file.
            if sha256_bytes(target.read_bytes()) == digest:
                return
            target = resolve_conflict_path(target)
        try:
            atomic_write_bytes(target, raw_path.read_bytes())
        except (MailSyncError, OSError) as exc:
            logger.warning("import to pending failed for %s: %s", display, exc)
            return
        write_source_sidecar(
            target,
            build_source_info(
                account_label=account.label or mask_email(account.email),
                account_email=account.email,
                folder_name=folder.name,
                uid=message.uid,
                message=message,
                attachment_name=display,
                sha256=digest,
                downloaded_at=datetime.now().isoformat(timespec="seconds"),
            ),
        )

    def _retry_failed(self, account: MailAccountConfig) -> None:
        """Re-attempt previously failed downloads within the attempt cap."""
        failures = self.store.retryable_failures(
            account.account_id, self.options.failed_retry_limit
        )
        for record in failures:
            self._checkpoint()
            folder = self.store.get_folder_by_id(record.folder_id)
            if folder is None:
                continue
            if self._selected_folder != folder.name:
                try:
                    self._with_retry(
                        f"重新打开文件夹 {folder.name}",
                        lambda name=folder.name: self._client.select_folder(name),
                    )
                    self._selected_folder = folder.name
                except MailSyncError:
                    continue
            message = MessageInfo(
                uid=record.uid,
                message_id=record.message_id,
                subject=record.subject,
                sender=record.sender,
                date=record.message_date,
            )
            if not record.part_number:
                continue
            part = _part_from_record(record)
            task_id = self.store.create_task(
                account.account_id, folder.id, folder.name, MODE_RETRY
            )
            self._download_candidate(account, folder, message, part, task_id)
            self.store.update_task(task_id, status=store_mod.TASK_DONE)

    # ------------------------------------------------------------------
    # Helpers

    def _checkpoint(self) -> None:
        """Cancellation + pause point between work items."""
        raise_if_cancelled(self.cancel_event)
        while self.pause_event.is_set():
            self.snapshot.paused = True
            raise_if_cancelled(self.cancel_event)
            time.sleep(0.2)
        if self.snapshot.paused:
            self.snapshot.paused = False

    def _bump_task(self, task_id: int, field: str, amount: int = 1) -> int:
        """Atomically increment a counter on a task row."""
        row = self.store.get_task(task_id)
        new_value = int(row.get(field) or 0) + amount
        self.store.update_task(task_id, **{field: new_value})
        if field == "processed":
            self.snapshot.processed += amount
        return new_value


class _RecordPart:
    """AttachmentPart-shaped stub rebuilt from a stored record."""

    def __init__(self, record) -> None:
        self.index = record.attachment_index
        self.part_number = record.part_number
        self.filename = record.attachment_name
        self.size = record.size
        self.content_type = ""
        self.is_inline_with_name = False


def _part_from_record(record) -> _RecordPart:
    return _RecordPart(record)


def _parse_message_info(uid: int, header_bytes: bytes) -> MessageInfo:
    """Parse SUBJECT/FROM/DATE/MESSAGE-ID headers into a MessageInfo."""
    info = MessageInfo(uid=uid)
    try:
        message = email.parser.BytesParser(policy=email.policy.default).parsebytes(
            header_bytes
        )
    except Exception:  # noqa: BLE001
        return info
    subject = message.get("Subject")
    if subject is not None:
        info.subject = _decode_header_value(str(subject))
    sender = message.get("From")
    if sender is not None:
        _name, addr = email.utils.parseaddr(str(sender))
        info.sender = addr or str(sender)
    date_header = message.get("Date")
    if date_header is not None:
        info.date = str(date_header).strip()
    message_id = message.get("Message-ID")
    if message_id is not None:
        info.message_id = str(message_id).strip()
    return info


def _decode_header_value(value: str) -> str:
    from mail.attachment import decode_mime_words

    try:
        return decode_mime_words(value)
    except Exception:  # noqa: BLE001
        return value
