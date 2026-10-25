"""Tests for MailService orchestration (accounts, scheduling, conflicts)."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from config.schema import AppConfig
from core.errors import OperationCancelled
from mail.credentials import InMemoryCredentialStore
from mail.errors import MailErrorCode
from mail.models import MailAccountConfig, SyncStatusSnapshot
from services.mail_service import MailService
from tests.mail.conftest import seed_account, seed_folder
from tests.mail.fake_imap_server import FakeMessage
from utils.paths import RuntimePaths


@pytest.fixture(autouse=True)
def _clear_engine_runs():
    _FakeEngine.runs = []
    yield


class _FakeEngine:
    """Engine stub honoring cancel/pause events; records each run."""

    runs: list = []

    def __init__(self, **kwargs):
        self.snapshot = kwargs["snapshot"]
        self.cancel_event = kwargs["cancel_event"]
        self._gate = kwargs.get("gate")
        self.kwargs = kwargs

    def run(self, account, mode, since=None, until=None):
        _FakeEngine.runs.append((account.account_id, mode))
        deadline = time.time() + 5
        while not self.cancel_event.is_set():
            if self._gate is None or self._gate.is_set():
                return self.snapshot
            if time.time() > deadline:
                raise TimeoutError
            time.sleep(0.02)
        raise OperationCancelled()


def _service(tmp_path: Path, config: AppConfig, gate=None) -> MailService:
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure_dirs()
    credentials = InMemoryCredentialStore()
    gate_holder = {"gate": gate}

    def engine_factory(**kwargs):
        kwargs["gate"] = gate_holder["gate"]
        return _FakeEngine(**kwargs)

    saved: list = []
    return MailService(
        runtime_paths=paths,
        config_getter=lambda: config,
        config_saver=lambda cfg: saved.append(cfg),
        credential_store=credentials,
        client_factory=lambda *a, **k: None,
        engine_factory=engine_factory,
    )


def _account(email="a@163.com") -> MailAccountConfig:
    account = MailAccountConfig()
    account.email = email
    account.host = "127.0.0.1"
    account.port = 1
    account.folders = ["INBOX"]
    return account


def test_account_crud_and_secret_storage(tmp_path) -> None:
    config = AppConfig()
    service = _service(tmp_path, config)
    account = _account()
    persisted = []
    service.upsert_account(
        account, secret="code-1", persist=lambda c: persisted.append(c)
    )
    assert service.list_accounts()[0].account_id == account.account_id
    assert service.credential_available(account.account_id)
    assert persisted
    service.delete_account(account.account_id)
    assert service.list_accounts() == []
    assert not service.credential_available(account.account_id)
    service.shutdown()


def test_incremental_run_updates_account_state(tmp_path) -> None:
    config = AppConfig()
    service = _service(tmp_path, config)
    account = _account()
    service.upsert_account(account, secret="s")
    assert service.start_incremental(account.account_id)
    deadline = time.time() + 5
    while time.time() < deadline and service.running:
        time.sleep(0.05)
    assert _FakeEngine.runs == [(account.account_id, "incremental")]
    stored = service.get_account(account.account_id)
    assert stored.last_sync_at
    assert stored.last_error == ""
    service.shutdown()


def test_same_account_conflict_rejected(tmp_path) -> None:
    config = AppConfig()
    gate = threading.Event()
    service = _service(tmp_path, config, gate=gate)
    account = _account()
    service.upsert_account(account, secret="s")
    assert service.start_incremental(account.account_id)
    assert not service.start_incremental(account.account_id)  # conflict
    gate.set()
    deadline = time.time() + 5
    while time.time() < deadline and service.running:
        time.sleep(0.05)
    service.shutdown()
    assert len(_FakeEngine.runs) == 1


def test_sync_due_accounts_respects_interval(tmp_path) -> None:
    config = AppConfig()
    service = _service(tmp_path, config)
    fresh = _account("fresh@163.com")
    fresh.last_sync_at = datetime.now().isoformat()
    fresh.sync_interval_minutes = 60
    stale = _account("stale@163.com")
    stale.last_sync_at = (datetime.now() - timedelta(hours=2)).isoformat()
    disabled = _account("off@163.com")
    disabled.enabled = False
    for a in (fresh, stale, disabled):
        service.upsert_account(a, secret="s")
    assert service.sync_due_accounts() == 1
    # Auto-sync master switch off → nothing is queued.
    service.set_auto_sync(False, 15)
    assert service.sync_due_accounts() == 0
    service.shutdown()


def test_cancel_marks_account_cancelled(tmp_path) -> None:
    config = AppConfig()
    gate = threading.Event()  # never set → engine idles until cancelled
    service = _service(tmp_path, config, gate=gate)
    account = _account()
    service.upsert_account(account, secret="s")
    assert service.start_incremental(account.account_id)
    deadline = time.time() + 5
    while time.time() < deadline and not service.running:
        time.sleep(0.02)
    service.cancel()
    deadline = time.time() + 5
    while time.time() < deadline and service.running:
        time.sleep(0.05)
    stored = service.get_account(account.account_id)
    assert stored.last_error == "已取消"
    service.shutdown()


def test_test_connection_full_probe(tmp_path, fake_server) -> None:
    seed_account(fake_server, email="a@163.com", secret="code")
    seed_folder(fake_server, "INBOX", [FakeMessage(uid=1)])
    config = AppConfig()
    service = _service(tmp_path, config)
    from mail.imap_client import ImapClient

    service._client_factory = lambda h, p, s, t: ImapClient(h, p, s, t)
    account = _account("a@163.com")
    account.host = fake_server.host
    account.port = fake_server.port
    account.use_ssl = False
    result = service.test_connection(account, "code")
    assert result.ok
    assert result.folders
    bad = service.test_connection(account, "wrong")
    assert not bad.ok
    assert bad.code == MailErrorCode.AUTH_FAILED
    service.shutdown()


def test_repair_invalid_downloads_marks_only_corrupt(tmp_path) -> None:
    """done records whose stored file is base64 text or a broken PDF are
    marked failed for re-download; healthy records are untouched."""
    import base64

    from tests.mail.conftest import VALID_PDF

    config = AppConfig()
    service = _service(tmp_path, config)
    account = _account()
    service.upsert_account(account, secret="s")
    folder = service.store.upsert_folder(account.account_id, "INBOX")

    def make_record(uid: int, name: str):
        return service.store.upsert_attachment(
            account_id=account.account_id,
            folder_id=folder.id,
            uidvalidity=1,
            uid=uid,
            message_id="",
            subject="",
            sender="",
            message_date="",
            attachment_index=0,
            attachment_name=name,
            part_number="2",
            size=10,
        )

    corrupt_dir = tmp_path / "raw"
    corrupt_dir.mkdir()

    # 1. base64 text stored under a literal-corrupted name (live bug shape).
    bad_file = corrupt_dir / "u1_a0_{266}truncated"
    bad_file.write_bytes(base64.b64encode(VALID_PDF))
    bad = make_record(1, "{266}truncated")
    service.store.mark_attachment(
        bad.id, "done", local_path=str(bad_file), content_hash="x1"
    )

    # 2. a real PDF that must stay done.
    good_file = corrupt_dir / "u2_a0_real.pdf"
    good_file.write_bytes(VALID_PDF)
    good = make_record(2, "real.pdf")
    service.store.mark_attachment(
        good.id, "done", local_path=str(good_file), content_hash="x2"
    )

    # 3. a .pdf-named file whose content is broken.
    broken_file = corrupt_dir / "u3_a0_broken.pdf"
    broken_file.write_bytes(b"garbage")
    broken = make_record(3, "broken.pdf")
    service.store.mark_attachment(
        broken.id, "done", local_path=str(broken_file), content_hash="x3"
    )

    # 4. non-pdf done record left alone even if content is arbitrary.
    other_file = corrupt_dir / "u4_a0_note.txt"
    other_file.write_bytes(b"not a pdf and never meant to be")
    other = make_record(4, "note.txt")
    service.store.mark_attachment(
        other.id, "done", local_path=str(other_file), content_hash="x4"
    )

    repaired = service._repair_invalid_downloads(account.account_id)
    assert repaired == 2
    assert service.store.get_attachment(bad.id).download_status == "failed"
    assert service.store.get_attachment(broken.id).download_status == "failed"
    assert service.store.get_attachment(good.id).download_status == "done"
    assert service.store.get_attachment(other.id).download_status == "done"
    # Originals were not deleted.
    assert bad_file.exists() and broken_file.exists()
    service.shutdown()
