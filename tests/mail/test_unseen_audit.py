"""End-to-end UnseenAuditRunner tests against the fake IMAP server."""

from __future__ import annotations

from pathlib import Path

import pytest

from mail.store import STATUS_DONE
from mail.unseen_audit import UnseenAuditRunner
from tests.mail.conftest import VALID_PDF, seed_account, seed_folder
from tests.mail.fake_imap_server import FakeAttachment, FakeMessage

INVOICE_TEXT = "电子发票（普通发票） 发票号码：26317000001234567890 价税合计（大写） 壹佰圆整 ¥100.00"
VOUCHER_TEXT = "滴滴出行-行程单 DIDI TRAVEL 共1笔行程，合计44.50元 行程报销单" * 2


def _runner(tmp_path, account, store, client) -> UnseenAuditRunner:
    return UnseenAuditRunner(
        client=client,
        store=store,
        account=account,
        invoice_root=tmp_path,
        raw_dir_name="raw",
        pending_dir_name="pending",
        review_dir_name="review",
        text_extractor=lambda p: _TEXTS.get(p.name, ""),
    )


_TEXTS: dict[str, str] = {}


def _client(fake_server, account):
    from mail.imap_client import ImapClient

    c = ImapClient(account.host, account.port, account.use_ssl, 5.0)
    c.connect()
    c.login(account.email, "auth-code-1")
    c.send_id()
    return c


@pytest.fixture(autouse=True)
def _clear_texts():
    _TEXTS.clear()


def test_unseen_only_scanned_and_routed(tmp_path, sync_store, fake_server, account):
    seed_account(fake_server)
    unseen_invoice = FakeMessage(
        uid=10, unseen=True, message_id="u10@x",
        attachments=[FakeAttachment("发票A.pdf", "application/pdf", VALID_PDF)],
    )
    seen_msg = FakeMessage(
        uid=11, unseen=False, message_id="u11@x",
        attachments=[FakeAttachment("seen.pdf", "application/pdf", VALID_PDF)],
    )
    unseen_no_pdf = FakeMessage(uid=12, unseen=True, message_id="u12@x")
    seed_folder(fake_server, "INBOX", [unseen_invoice, seen_msg, unseen_no_pdf])

    client = _client(fake_server, account)
    result = _runner(tmp_path, account, sync_store, client).run("INBOX")
    client.logout()

    assert result.unseen_frozen == 2
    assert result.scanned == 2  # uid 11 (seen) never touched
    assert result.msgs_with_pdf == 1
    assert result.pdf_parts == 1
    assert result.downloaded == 1
    assert result.dedup_skipped == 0
    raw = list((tmp_path / "raw").rglob("*.pdf"))
    assert len(raw) == 1
    assert raw[0].read_bytes() == VALID_PDF
    # no STORE commands — server-side read state untouched
    assert not any("STORE" in cmd.upper() for cmd in fake_server.command_log)


def test_classification_routes_einvoice_pending_others_review(
    tmp_path, sync_store, fake_server, account
):
    seed_account(fake_server)
    msgs = [
        FakeMessage(uid=20, unseen=True, message_id="i@x",
                    attachments=[FakeAttachment("inv.pdf", "application/pdf",
                                                VALID_PDF + b"1")]),
        FakeMessage(uid=21, unseen=True, message_id="v@x",
                    attachments=[FakeAttachment("voucher.pdf", "application/pdf",
                                                VALID_PDF + b"2")]),
        FakeMessage(uid=22, unseen=True, message_id="o@x",
                    attachments=[FakeAttachment("other.pdf", "application/pdf",
                                                VALID_PDF + b"3")]),
    ]
    _TEXTS.update({
        "inv.pdf": INVOICE_TEXT, "voucher.pdf": VOUCHER_TEXT,
        "other.pdf": "generic document content " * 20,
    })
    # filenames written are u<uid>_a0_<name>.pdf — map by suffix
    text_lookup = {"inv": INVOICE_TEXT, "voucher": VOUCHER_TEXT,
                   "other": "generic document content " * 20}
    seed_folder(fake_server, "INBOX", msgs)

    def extractor(p: Path) -> str:
        for key, value in text_lookup.items():
            if key in p.name:
                return value
        return ""

    client = _client(fake_server, account)
    runner = UnseenAuditRunner(
        client=client, store=sync_store, account=account,
        invoice_root=tmp_path, raw_dir_name="raw",
        pending_dir_name="pending", review_dir_name="review",
        text_extractor=extractor,
    )
    result = runner.run("INBOX")
    client.logout()

    assert result.downloaded == 3
    assert result.classified["e_invoice"] == 1
    assert result.classified["travel_voucher"] == 1
    assert result.classified["other_pdf"] == 1
    assert result.pending_copies == 1
    assert result.review_copies == 2
    pending = list((tmp_path / "pending").glob("*.pdf"))
    review = list((tmp_path / "review").glob("*.pdf"))
    assert len(pending) == 1 and "inv" in pending[0].name
    assert len(review) == 2
    assert len(list((tmp_path / "review").glob("*.source.json"))) == 2


def test_existing_done_record_deduped_not_redownloaded(
    tmp_path, sync_store, fake_server, account
):
    seed_account(fake_server)
    msg = FakeMessage(uid=30, unseen=True, message_id="d@x",
                      attachments=[FakeAttachment("dup.pdf", "application/pdf", VALID_PDF)])
    folder = seed_folder(fake_server, "INBOX", [msg])

    existing = tmp_path / "raw" / "already.pdf"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(VALID_PDF)
    db_folder = sync_store.upsert_folder(account.account_id, "INBOX")
    sync_store.update_folder_state(db_folder.id, uidvalidity=1001)
    rec = sync_store.upsert_attachment(
        account_id=account.account_id, folder_id=db_folder.id, uidvalidity=1001,
        uid=30, message_id="d@x", subject="", sender="", message_date="",
        attachment_index=0, attachment_name="dup.pdf", part_number="2", size=10,
    )
    sync_store.mark_attachment(rec.id, STATUS_DONE, local_path=str(existing))
    fetch_log_before = len(fake_server.command_log)

    client = _client(fake_server, account)
    result = _runner(tmp_path, account, sync_store, client).run("INBOX")
    client.logout()

    assert result.dedup_skipped == 1
    assert result.downloaded == 0
    # BODY[2] part fetch never happened for the deduped record
    assert not any("BODY.PEEK[2]" in c for c in fake_server.command_log[fetch_log_before:])


def test_invoice_link_candidate_listed_not_fetched(
    tmp_path, sync_store, fake_server, account
):
    seed_account(fake_server)
    msg = FakeMessage(
        uid=40, unseen=True, message_id="l@x", subject="发票下载",
        body_text="电子发票下载 https://fp.example.com/dzfp/abc123",
    )
    seed_folder(fake_server, "INBOX", [msg])
    client = _client(fake_server, account)
    result = _runner(tmp_path, account, sync_store, client).run("INBOX")
    client.logout()
    assert result.link_candidates == [
        {"uid": 40, "subject": "发票下载",
         "links": ["https://fp.example.com/dzfp/abc123"]}
    ]


def test_unseen_set_compared_after_run(tmp_path, sync_store, fake_server, account):
    seed_account(fake_server)
    folder = seed_folder(fake_server, "INBOX",
                         [FakeMessage(uid=50, unseen=True, message_id="a@x")])
    client = _client(fake_server, account)
    result = _runner(tmp_path, account, sync_store, client).run("INBOX")
    assert result.unseen_same
    client.logout()

    # new unseen mail arrives mid-run → difference reported, not hidden
    folder.messages.append(FakeMessage(uid=51, unseen=True, message_id="b@x"))
    client = _client(fake_server, account)
    result = _runner(tmp_path, account, sync_store, client).run("INBOX")
    assert result.unseen_frozen == 2
    assert result.unseen_same
    client.logout()
