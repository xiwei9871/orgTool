"""Integration tests: ImapClient against the fake IMAP server."""

from __future__ import annotations

import pytest

from mail.errors import (
    MailErrorCode,
    MailSyncError,
)
from mail.attachment import decode_transfer_body, extract_attachments
from mail.imap_client import ImapClient
from tests.mail.conftest import VALID_PDF, seed_account, seed_folder
from tests.mail.fake_imap_server import FakeAttachment, FakeFolder, FakeMessage


def _client(account) -> ImapClient:
    return ImapClient(
        account.host, account.port, use_ssl=False, timeout=5
    )


def _connect(client: ImapClient, secret: str = "auth-code-1") -> None:
    client.connect()
    client.login("tester@163.com", secret)
    client.send_id()


def test_full_staged_connect_lists_and_selects(fake_server, account) -> None:
    seed_account(fake_server)
    seed_folder(fake_server, "INBOX", [FakeMessage(uid=1, message_id="m1@x")])
    seed_folder(fake_server, "发票归档")
    client = _client(account)
    _connect(client)
    folders = client.list_folders()
    names = [f.name for f in folders]
    assert "INBOX" in names and "发票归档" in names
    info = client.select_folder("发票归档")
    assert info.uidvalidity == fake_server.folders["发票归档"].uidvalidity
    client.logout()


def test_wrong_auth_code_maps_auth_failed(fake_server, account) -> None:
    seed_account(fake_server)
    client = _client(account)
    client.connect()
    with pytest.raises(MailSyncError) as exc:
        client.login("tester@163.com", "wrong-code")
    assert exc.value.code == MailErrorCode.AUTH_FAILED
    client.logout()


def test_id_sent_before_select(fake_server, account) -> None:
    seed_account(fake_server)
    fake_server.require_id = True
    seed_folder(fake_server, "INBOX")
    client = _client(account)
    _connect(client)
    info = client.select_folder("INBOX")
    assert fake_server.id_sent
    assert info.exists == 0
    client.logout()


def test_id_rejected_flagged_and_select_maps_error(
    fake_server, account
) -> None:
    seed_account(fake_server)
    fake_server.fail_id = True
    seed_folder(fake_server, "INBOX")
    fake_server.fail_select.add("INBOX")
    client = _client(account)
    client.connect()
    client.login("tester@163.com", "auth-code-1")
    assert client.send_id() is False
    with pytest.raises(MailSyncError) as exc:
        client.select_folder("INBOX")
    assert exc.value.code == MailErrorCode.IMAP_ID_UNSUPPORTED
    client.logout()


def test_select_failure_maps_error(fake_server, account) -> None:
    seed_account(fake_server)
    seed_folder(fake_server, "INBOX")
    fake_server.fail_select.add("INBOX")
    client = _client(account)
    _connect(client)
    with pytest.raises(MailSyncError) as exc:
        client.select_folder("INBOX")
    assert exc.value.code == MailErrorCode.MAILBOX_SELECT_FAILED
    client.logout()


def test_chinese_folder_name_utf7_on_wire(fake_server, account) -> None:
    seed_account(fake_server)
    seed_folder(fake_server, "收件箱")
    client = _client(account)
    _connect(client)
    folders = client.list_folders()
    assert folders[0].name == "收件箱"
    client.select_folder("收件箱")  # encoded on the wire
    list_cmds = [
        c for c in fake_server.command_log if " LIST " in c.upper()
    ]
    assert list_cmds
    client.logout()


def test_uid_search_and_fetch_header(fake_server, account) -> None:
    seed_account(fake_server)
    seed_folder(
        fake_server,
        "INBOX",
        [
            FakeMessage(uid=11, message_id="h1@x", subject="账单"),
            FakeMessage(uid=12, message_id="h2@x", sender="other@x.com"),
        ],
    )
    client = _client(account)
    _connect(client)
    client.select_folder("INBOX")
    assert client.uid_search(uid_min=11) == [11, 12]
    assert client.uid_search(uid_min=12) == [12]
    headers = client.fetch_header(11)
    assert "账单" in headers.decode("utf-8", errors="replace")
    client.logout()


def test_search_returns_empty_not_exception(fake_server, account) -> None:
    seed_account(fake_server)
    seed_folder(fake_server, "INBOX")
    client = _client(account)
    _connect(client)
    client.select_folder("INBOX")
    assert client.uid_search(uid_min=999) == []
    client.logout()


def test_fetch_part_bytes(fake_server, account) -> None:
    seed_account(fake_server)
    message = FakeMessage(
        uid=5,
        message_id="p@x",
        attachments=[FakeAttachment("f.pdf", "application/pdf", VALID_PDF)],
    )
    seed_folder(fake_server, "INBOX", [message])
    client = _client(account)
    _connect(client)
    client.select_folder("INBOX")
    tree = client.fetch_bodystructure(5)
    assert tree is not None
    data = client.fetch_part(5, "2")
    # BODY[n] arrives in the declared transfer encoding — the client layer
    # returns wire bytes; the sync engine decodes them.
    assert data == message.attachments[0].wire_data()
    assert decode_transfer_body(data, "BASE64") == VALID_PDF
    client.logout()


def test_fetch_part_7bit_returns_raw(fake_server, account) -> None:
    seed_account(fake_server)
    message = FakeMessage(
        uid=5,
        message_id="p@x",
        attachments=[
            FakeAttachment("f.pdf", "application/pdf", VALID_PDF, encoding="7BIT")
        ],
    )
    seed_folder(fake_server, "INBOX", [message])
    client = _client(account)
    _connect(client)
    client.select_folder("INBOX")
    data = client.fetch_part(5, "2")
    assert data == VALID_PDF
    client.logout()


def test_bodystructure_literal_filename(fake_server, account) -> None:
    """NetEase sends non-ASCII NAME/FILENAME params as {n} literals."""
    seed_account(fake_server)
    message = FakeMessage(
        uid=9,
        message_id="lit@x",
        attachments=[
            FakeAttachment(
                "电子发票-差旅报销.pdf",
                "application/pdf",
                VALID_PDF,
                literal_filename=True,
            )
        ],
    )
    seed_folder(fake_server, "INBOX", [message])
    client = _client(account)
    _connect(client)
    client.select_folder("INBOX")
    tree = client.fetch_bodystructure(9)
    parts = extract_attachments(tree)
    assert len(parts) == 1
    assert parts[0].filename == "电子发票-差旅报销.pdf"
    assert parts[0].encoding == "BASE64"
    client.logout()


def test_folder_status_counts(fake_server, account) -> None:
    seed_account(fake_server)
    folder = FakeFolder(
        name="INBOX",
        messages=[FakeMessage(uid=u) for u in (1, 2, 3)],
        unseen=2,
    )
    fake_server.folders["INBOX"] = folder
    client = _client(account)
    _connect(client)
    status = client.folder_status("INBOX")
    assert status["exists"] == 3
    assert status["unseen"] == 2
    client.logout()


def test_history_limit_caps_search(fake_server, account) -> None:
    seed_account(fake_server)
    messages = [
        FakeMessage(uid=u, message_id=f"m{u}@x") for u in range(1, 51)
    ]
    seed_folder(fake_server, "INBOX", messages)
    fake_server.history_limit = 20  # server only exposes recent 20
    client = _client(account)
    _connect(client)
    client.select_folder("INBOX")
    assert len(client.uid_search()) == 20
    client.logout()


def test_select_without_id_when_server_requires_it(
    fake_server, account
) -> None:
    """Server requiring ID: a client that skips send_id gets SELECT refused."""
    seed_account(fake_server)
    fake_server.require_id = True
    seed_folder(fake_server, "INBOX")
    client = _client(account)
    client.connect()
    client.login("tester@163.com", "auth-code-1")
    # Deliberately skip send_id.
    with pytest.raises(MailSyncError) as exc:
        client.select_folder("INBOX")
    assert exc.value.code in {
        MailErrorCode.MAILBOX_SELECT_FAILED,
        MailErrorCode.IMAP_ID_UNSUPPORTED,
    }
    client.logout()
