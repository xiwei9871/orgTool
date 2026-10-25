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
