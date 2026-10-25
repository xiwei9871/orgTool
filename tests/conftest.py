"""Shared fixtures for the whole test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from mail.models import MailAccountConfig
from mail.store import MailSyncStore
from tests.mail.fake_imap_server import FakeImapServer

VALID_PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n%%EOF\n"


@pytest.fixture()
def fake_server():
    server = FakeImapServer()
    server.start()
    yield server
    server.stop()


@pytest.fixture()
def sync_store(tmp_path: Path):
    store = MailSyncStore(tmp_path / "mail_sync.db")
    yield store
    store.close()


@pytest.fixture()
def account(fake_server) -> MailAccountConfig:
    acc = MailAccountConfig()
    acc.label = "测试账户"
    acc.email = "tester@163.com"
    acc.host = fake_server.host
    acc.port = fake_server.port
    acc.use_ssl = False
    acc.folders = ["INBOX"]
    return acc


def seed_account(server: FakeImapServer, email="tester@163.com", secret="auth-code-1"):
    server.users[email] = secret
    return secret


def seed_folder(server: FakeImapServer, name: str, messages=None, uidvalidity=1001):
    from tests.mail.fake_imap_server import FakeFolder

    folder = FakeFolder(name=name, uidvalidity=uidvalidity)
    folder.messages = list(messages or [])
    server.folders[name] = folder
    return folder
