"""Service orchestration for mail accounts, sync scheduling, and polling."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from core.errors import OperationCancelled
from mail.attachment import looks_like_pdf_bytes
from mail.credentials import CredentialStore, KeyringCredentialStore
from mail.errors import MailErrorCode, MailSyncError
from mail.imap_client import ImapClient
from mail.models import (
    ConnectionProbeResult,
    MailAccountConfig,
    MailConfig,
    MailFolder,
    SyncStatusSnapshot,
)
from mail.store import MailSyncStore
from mail.sync_engine import MODE_BACKFILL, MODE_INCREMENTAL, MailSyncEngine
from services.log_service import configure_file_logger
from utils.paths import RuntimePaths

logger = logging.getLogger(__name__)


@dataclass
class _SyncJob:
    """One queued/running synchronization request."""

    account: MailAccountConfig
    mode: str
    since: date | None = None
    until: date | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    pause_event: threading.Event = field(default_factory=threading.Event)
    snapshot: SyncStatusSnapshot = field(default_factory=SyncStatusSnapshot)
    future: Future | None = None


class MailService:
    """Coordinate mail account CRUD, credentials, sync, and scheduling.

    Sync work runs on a single-worker executor: jobs for different accounts
    queue sequentially while the same account can never be queued twice
    (``SYNC_CONFLICT``). The service never blocks the calling thread.
    """

    def __init__(
        self,
        runtime_paths: RuntimePaths,
        config_getter: Callable[[], object],
        config_saver: Callable[[object], None] | None = None,
        credential_store: CredentialStore | None = None,
        client_factory=None,
        engine_factory=None,
    ) -> None:
        self.paths = runtime_paths
        self._config_getter = config_getter
        self._config_saver = config_saver or (lambda config: None)
        self.store = MailSyncStore(runtime_paths.mail_sync_db)
        self.credentials = credential_store or KeyringCredentialStore()
        self._client_factory = client_factory or ImapClient
        self._engine_factory = engine_factory or MailSyncEngine
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="mail-sync"
        )
        self._jobs: list[_SyncJob] = []
        self._jobs_lock = threading.RLock()
        self._last_snapshot = SyncStatusSnapshot()
        self._shutdown = False
        self.logger = configure_file_logger(
            "mail", runtime_paths.logs_dir / "mail_sync.log"
        )

    # ------------------------------------------------------------------
    # Configuration access

    def _config(self) -> MailConfig:
        return self._config_getter().mail

    # ------------------------------------------------------------------
    # Account management

    def list_accounts(self) -> list[MailAccountConfig]:
        return list(self._config().accounts)

    def get_account(self, account_id: str) -> MailAccountConfig | None:
        for account in self._config().accounts:
            if account.account_id == account_id:
                return account
        return None

    def upsert_account(
        self,
        account: MailAccountConfig,
        secret: str | None = None,
        persist: Callable[[MailConfig], None] | None = None,
    ) -> None:
        """Create or update an account; store the auth code in the OS keychain."""
        config = self._config()
        replaced = False
        for index, existing in enumerate(config.accounts):
            if existing.account_id == account.account_id:
                config.accounts[index] = account
                replaced = True
                break
        if not replaced:
            config.accounts.append(account)
        if secret:
            self.credentials.set_secret(account.account_id, secret)
        if persist is not None:
            persist(config)

    def delete_account(
        self,
        account_id: str,
        persist: Callable[[MailConfig], None] | None = None,
    ) -> None:
        """Remove the account config and its stored credential."""
        config = self._config()
        config.accounts = [
            account for account in config.accounts if account.account_id != account_id
        ]
        try:
            self.credentials.delete_secret(account_id)
        except MailSyncError:
            self.logger.info("credential cleanup skipped for %s", account_id)
        if persist is not None:
            persist(config)

    def set_auto_sync(
        self,
        enabled: bool,
        interval_minutes: int,
        persist: Callable[[MailConfig], None] | None = None,
    ) -> None:
        config = self._config()
        config.auto_sync_enabled = enabled
        if interval_minutes > 0:
            config.poll_interval_minutes = interval_minutes
        if persist is not None:
            persist(config)

    def credential_available(self, account_id: str) -> bool:
        try:
            return bool(self.credentials.get_secret(account_id))
        except MailSyncError:
            return False

    # ------------------------------------------------------------------
    # Connection probing and folder discovery

    def _new_client(self, account: MailAccountConfig) -> ImapClient:
        return self._client_factory(
            account.host, account.port, account.use_ssl, 30.0
        )

    def test_connection(
        self, account: MailAccountConfig, secret: str | None
    ) -> ConnectionProbeResult:
        """Probe connect → login → ID → LIST → SELECT → UID SEARCH → UID FETCH."""
        client = self._new_client(account)
        try:
            client.connect()
        except MailSyncError as exc:
            return ConnectionProbeResult(False, "connect", exc.code, exc.message)
        try:
            client.login(account.email, secret or "")
        except MailSyncError as exc:
            client.logout()
            return ConnectionProbeResult(False, "login", exc.code, exc.message)
        try:
            id_ok = client.send_id()
            if id_ok is False:
                self.logger.warning(
                    "server did not accept IMAP ID for %s", account.host
                )
            try:
                folders = client.list_folders()
            except MailSyncError as exc:
                return ConnectionProbeResult(False, "list", exc.code, exc.message)
            selectable = [f for f in folders if f.selectable] or folders
            names = {f.name for f in selectable}
            target = (
                "INBOX" if "INBOX" in names else (selectable[0].name if selectable else "INBOX")
            )
            try:
                selected = client.select_folder(target)
            except MailSyncError as exc:
                return ConnectionProbeResult(False, "select", exc.code, exc.message)
            try:
                uids = client.uid_search()
                if uids:
                    client.fetch_header(uids[-1])
            except MailSyncError as exc:
                return ConnectionProbeResult(False, "uid_fetch", exc.code, exc.message)
            result = ConnectionProbeResult(
                ok=True,
                stage="done",
                message=(
                    f"连接成功；{len(folders)} 个文件夹，"
                    f"{target} 可见 {selected.exists} 封"
                ),
                folders=folders,
            )
            if id_ok is False:
                result.message += "；注意：服务器未确认 IMAP ID"
            return result
        finally:
            client.logout()

    def list_folders(
        self, account: MailAccountConfig, secret: str | None
    ) -> list[MailFolder]:
        """Discover selectable folders for folder selection UI."""
        client = self._new_client(account)
        try:
            client.connect()
            client.login(account.email, secret or "")
            client.send_id()
            return client.list_folders()
        finally:
            client.logout()

    # ------------------------------------------------------------------
    # Sync control

    @property
    def running(self) -> bool:
        with self._jobs_lock:
            return any(job.future and not job.future.done() for job in self._jobs)

    def start_backfill(
        self,
        account_id: str,
        since: date | None = None,
        until: date | None = None,
        folders: list[str] | None = None,
    ) -> bool:
        """Queue a historical backfill for one account. False = conflict."""
        account = self.get_account(account_id)
        if account is None:
            raise MailSyncError(MailErrorCode.SYNC_CONFLICT, "账户不存在")
        if folders is not None:
            account = replace(account, folders=list(folders))
        return self._submit(account, MODE_BACKFILL, since=since, until=until)

    def start_incremental(self, account_id: str | None = None) -> bool:
        """Queue incremental sync for one or all enabled accounts."""
        accounts = (
            [a for a in self.list_accounts() if a.account_id == account_id]
            if account_id
            else [a for a in self.list_accounts() if a.enabled]
        )
        submitted = False
        for account in accounts:
            submitted = self._submit(account, MODE_INCREMENTAL) or submitted
        return submitted

    def sync_due_accounts(self, now: datetime | None = None) -> int:
        """Queue incremental sync for accounts past their poll interval."""
        config = self._config()
        if not config.auto_sync_enabled or self._shutdown:
            return 0
        now = now or datetime.now()
        submitted = 0
        for account in config.accounts:
            if not account.enabled:
                continue
            if self._is_due(account, now, config.poll_interval_minutes):
                submitted += 1 if self._submit(account, MODE_INCREMENTAL) else 0
        return submitted

    def _is_due(
        self, account: MailAccountConfig, now: datetime, default_interval: int
    ) -> bool:
        if not account.last_sync_at:
            return True
        try:
            last = datetime.fromisoformat(account.last_sync_at)
        except ValueError:
            return True
        interval = max(1, account.sync_interval_minutes or default_interval)
        return (now - last).total_seconds() >= interval * 60

    def pause(self) -> None:
        """Pause the active sync cooperatively between work items."""
        with self._jobs_lock:
            for job in self._jobs:
                job.pause_event.set()
                job.snapshot.paused = True

    def resume(self) -> None:
        with self._jobs_lock:
            for job in self._jobs:
                job.pause_event.clear()
                job.snapshot.paused = False

    def cancel(self) -> None:
        """Cancel the active sync and drop every queued job."""
        with self._jobs_lock:
            for job in list(self._jobs):
                job.pause_event.clear()
                job.cancel_event.set()
                if job.future is not None and not job.future.running():
                    job.future.cancel()
                    self._jobs.remove(job)

    def status(self) -> SyncStatusSnapshot:
        """Return the snapshot of the currently running (or last) job."""
        with self._jobs_lock:
            for job in self._jobs:
                if job.future is not None and not job.future.done():
                    snapshot = job.snapshot
                    snapshot.running = True
                    return snapshot
            return self._last_snapshot

    def shutdown(self, timeout: float = 5.0) -> None:
        """Cancel and wait briefly for in-flight sync work."""
        self._shutdown = True
        with self._jobs_lock:
            jobs = list(self._jobs)
        for job in jobs:
            job.pause_event.clear()
            job.cancel_event.set()
        self._executor.shutdown(wait=False, cancel_futures=True)
        for job in jobs:
            if job.future is not None:
                try:
                    job.future.result(timeout=timeout)
                except Exception:
                    pass
        with self._jobs_lock:
            self._jobs.clear()

    # ------------------------------------------------------------------
    # Internals

    def _submit(
        self,
        account: MailAccountConfig,
        mode: str,
        since: date | None = None,
        until: date | None = None,
    ) -> bool:
        with self._jobs_lock:
            if self._shutdown:
                return False
            for job in self._jobs:
                if job.account.account_id == account.account_id and (
                    job.future is None or not job.future.done()
                ):
                    self._last_snapshot.last_error = "该账户已有同步任务在执行"
                    self._last_snapshot.last_error_code = MailErrorCode.SYNC_CONFLICT
                    return False
            job = _SyncJob(account=account, mode=mode, since=since, until=until)
            job.snapshot.running = True
            job.snapshot.account_label = account.label or account.email
            job.snapshot.mode = mode
            job.future = self._executor.submit(self._run_sync, job)
            self._jobs.append(job)
            return True

    def _run_sync(self, job: _SyncJob) -> None:
        account = job.account
        engine = self._engine_factory(
            store=self.store,
            invoice_root=Path(self._config_getter().invoice.root_dir or "."),
            pending_dir_name=self._config_getter().invoice.pending_dir_name,
            raw_dir_name=self._config().raw_dir_name,
            cancel_event=job.cancel_event,
            pause_event=job.pause_event,
            snapshot=job.snapshot,
            client_factory=self._client_factory,
            secret_getter=lambda aid: self.credentials.get_secret(aid),
        )
        repaired = self._repair_invalid_downloads(account.account_id)
        if repaired:
            self.logger.info(
                "marked %s corrupt downloads for re-download", repaired
            )
        try:
            engine.run(account, job.mode, job.since, job.until)
            self._finish_account(
                account.account_id,
                last_sync_at=datetime.now().isoformat(timespec="seconds"),
                last_error="",
                last_error_code="",
            )
            self.logger.info("sync %s done for %s", job.mode, account.email)
        except OperationCancelled:
            self._finish_account(
                account.account_id, last_error="已取消", last_error_code=""
            )
            self.logger.info("sync %s cancelled for %s", job.mode, account.email)
        except MailSyncError as exc:
            self._finish_account(
                account.account_id,
                last_error=exc.message,
                last_error_code=exc.code,
            )
            job.snapshot.last_error = exc.message
            job.snapshot.last_error_code = exc.code
            self.logger.warning(
                "sync %s failed for %s: %s", job.mode, account.email, exc
            )
        except Exception as exc:  # noqa: BLE001
            self._finish_account(
                account.account_id,
                last_error=f"内部错误: {type(exc).__name__}",
                last_error_code=MailErrorCode.DOWNLOAD_INTERRUPTED,
            )
            job.snapshot.last_error = str(exc)
            job.snapshot.last_error_code = MailErrorCode.DOWNLOAD_INTERRUPTED
            self.logger.exception("unexpected sync failure for %s", account.email)
        finally:
            job.snapshot.running = False
            job.snapshot.paused = False
            with self._jobs_lock:
                self._last_snapshot = job.snapshot
                if job in self._jobs:
                    self._jobs.remove(job)

    def _repair_invalid_downloads(self, account_id: str) -> int:
        """Mark 'done' records whose stored file is not a real PDF for retry.

        Earlier builds wrote base64-encoded bodies and BODYSTRUCTURE literal
        fragments (e.g. ``{266}``) as filenames — the files exist but are not
        usable PDFs, so they must be re-downloaded instead of being trusted
        as done. Original files are left untouched on disk.
        """
        repaired = 0
        for record in self.store.done_records(account_id):
            if not record.local_path:
                continue
            path = Path(record.local_path)
            if not path.is_file():
                continue
            try:
                data = path.read_bytes()
            except OSError:
                continue
            if looks_like_pdf_bytes(data):
                continue
            is_base64_pdf = data.lstrip().startswith(b"JVBER")
            is_named_pdf = record.attachment_name.casefold().endswith(".pdf")
            if not (is_base64_pdf or is_named_pdf):
                continue
            self.store.mark_attachment(
                record.id,
                "failed",
                last_error="本地文件内容无效，待重新下载",
                last_error_code=MailErrorCode.INVALID_PDF,
            )
            repaired += 1
        return repaired

    def _finish_account(self, account_id: str, **fields) -> None:
        config = self._config()
        for account in config.accounts:
            if account.account_id == account_id:
                for key, value in fields.items():
                    setattr(account, key, value)
        self._config_saver(self._config_getter())
