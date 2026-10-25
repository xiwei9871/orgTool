"""End-to-end sync engine tests against the fake IMAP server."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from core.errors import OperationCancelled
from mail.models import MailAccountConfig
from mail.store import (
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_SKIPPED_DUPLICATE,
)
from mail.sync_engine import (
    MODE_BACKFILL,
    MODE_INCREMENTAL,
    EngineOptions,
    MailSyncEngine,
)
from tests.mail.conftest import VALID_PDF, seed_account, seed_folder
from tests.mail.fake_imap_server import FakeAttachment, FakeMessage


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("mail.sync_engine.time.sleep", lambda _s: None)


def _engine(
    tmp_path: Path,
    account: MailAccountConfig,
    store,
    cancel: threading.Event | None = None,
    **option_overrides,
) -> MailSyncEngine:
    options = EngineOptions(batch_size=10, retry_attempts=2)
    for key, value in option_overrides.items():
        setattr(options, key, value)
    return MailSyncEngine(
        store=store,
        invoice_root=tmp_path,
        pending_dir_name="pending",
        raw_dir_name="raw",
        cancel_event=cancel or threading.Event(),
        options=options,
        secret_getter=lambda _aid: "auth-code-1",
    )


def _msg(uid: int, filename="发票.pdf", data: bytes | None = "auto", **kw) -> FakeMessage:
    if data == "auto":
        data = f"%PDF-1.4\nuid-{uid} body\n%%EOF".encode()
    return FakeMessage(
        uid=uid,
        message_id=kw.pop("message_id", f"m{uid}@x"),
        subject=kw.pop("subject", f"账单{uid}"),
        sender=kw.pop("sender", "shop@x.com"),
        attachments=[FakeAttachment(filename, "application/pdf", data)]
        if data is not None
        else [],
        **kw,
    )


def test_backfill_downloads_pdf_to_raw_and_pending(
    tmp_path, sync_store, fake_server, account
) -> None:
    seed_account(fake_server)
    seed_folder(fake_server, "INBOX", [_msg(1), _msg(2)])
    snap = _engine(tmp_path, account, sync_store).run(
        account, MODE_BACKFILL
    )
    assert snap.downloaded == 2
    raw_files = list((tmp_path / "raw").rglob("*.pdf"))
    pending_files = list((tmp_path / "pending").glob("*.pdf"))
    assert len(raw_files) == 2 and len(pending_files) == 2
    sidecars = list((tmp_path / "pending").glob("*.source.json"))
    assert len(sidecars) == 2


def test_second_run_is_fully_idempotent(
    tmp_path, sync_store, fake_server, account
) -> None:
    seed_account(fake_server)
    seed_folder(fake_server, "INBOX", [_msg(1), _msg(2)])
    _engine(tmp_path, account, sync_store).run(account, MODE_BACKFILL)
    second = _engine(tmp_path, account, sync_store).run(
        account, MODE_BACKFILL
    )
    assert second.downloaded == 0
    assert len(list((tmp_path / "pending").glob("*.pdf"))) == 2


def test_same_content_different_message_deduped(
    tmp_path, sync_store, fake_server, account
) -> None:
    seed_account(fake_server)
    seed_folder(
        fake_server,
        "INBOX",
        [_msg(1, "a.pdf", VALID_PDF), _msg(2, "b.pdf", VALID_PDF)],
    )
    snap = _engine(tmp_path, account, sync_store).run(account, MODE_BACKFILL)
    assert snap.downloaded == 1
    assert snap.skipped_duplicate == 1
    assert len(list((tmp_path / "pending").glob("*.pdf"))) == 1


def test_same_name_different_content_both_kept(
    tmp_path, sync_store, fake_server, account
) -> None:
    pdf2 = b"%PDF-1.4\nother content\n%%EOF"
    seed_account(fake_server)
    seed_folder(
        fake_server,
        "INBOX",
        [_msg(1, "账单.pdf", VALID_PDF), _msg(2, "账单.pdf", pdf2)],
    )
    snap = _engine(tmp_path, account, sync_store).run(account, MODE_BACKFILL)
    assert snap.downloaded == 2
    names = sorted(p.name for p in (tmp_path / "pending").glob("*.pdf"))
    assert len(names) == 2 and names[0] != names[1]


def test_invalid_pdf_marked_failed_not_saved(
    tmp_path, sync_store, fake_server, account
) -> None:
    seed_account(fake_server)
    seed_folder(fake_server, "INBOX", [_msg(1, "fake.pdf", b"not a pdf body")])
    snap = _engine(tmp_path, account, sync_store).run(account, MODE_BACKFILL)
    assert snap.downloaded == 0
    assert snap.failed == 1
    assert not list((tmp_path / "pending").glob("*.pdf"))


def test_non_pdf_attachment_filtered(
    tmp_path, sync_store, fake_server, account
) -> None:
    seed_account(fake_server)
    message = FakeMessage(
        uid=1, message_id="m1@x",
        attachments=[FakeAttachment("doc.docx", "application/msword", b"doc")],
    )
    seed_folder(fake_server, "INBOX", [message])
    snap = _engine(tmp_path, account, sync_store).run(account, MODE_BACKFILL)
    assert snap.downloaded == 0
    assert snap.failed == 0


def test_uidvalidity_change_rescans_and_hash_dedups(
    tmp_path, sync_store, fake_server, account
) -> None:
    seed_account(fake_server)
    folder = seed_folder(fake_server, "INBOX", [_msg(1)], uidvalidity=1001)
    _engine(tmp_path, account, sync_store).run(account, MODE_BACKFILL)
    folder.uidvalidity = 2002  # server regenerated UIDs
    snap = _engine(tmp_path, account, sync_store).run(account, MODE_BACKFILL)
    assert snap.downloaded == 0
    assert snap.skipped_duplicate >= 1


def test_cancel_mid_run_resumes_without_loss_or_dup(
    tmp_path, sync_store, fake_server, account
) -> None:
    seed_account(fake_server)
    seed_folder(fake_server, "INBOX", [_msg(u) for u in range(1, 9)])
    cancel = threading.Event()
    engine = _engine(
        tmp_path, account, sync_store, cancel=cancel, batch_size=2
    )
    original = engine._download_candidate

    def download_then_cancel(*args, **kwargs):
        result = original(*args, **kwargs)
        counts = sync_store.count_by_status(account.account_id)
        if counts.get(STATUS_DONE, 0) >= 2:
            cancel.set()
        return result

    engine._download_candidate = download_then_cancel  # type: ignore[assignment]
    with pytest.raises(OperationCancelled):
        engine.run(account, MODE_BACKFILL)

    done = sync_store.count_by_status(account.account_id).get(STATUS_DONE, 0)
    assert done >= 2

    # Resume with a fresh engine — completes the rest without duplicates.
    snap = _engine(tmp_path, account, sync_store).run(account, MODE_BACKFILL)
    assert snap.downloaded + done == 8
    assert len(list((tmp_path / "pending").glob("*.pdf"))) == 8


def test_incremental_sync_fetches_only_new(
    tmp_path, sync_store, fake_server, account
) -> None:
    seed_account(fake_server)
    folder = seed_folder(fake_server, "INBOX", [_msg(1), _msg(2)])
    _engine(tmp_path, account, sync_store).run(account, MODE_INCREMENTAL)
    folder.messages.append(_msg(3))
    snap = _engine(tmp_path, account, sync_store).run(
        account, MODE_INCREMENTAL
    )
    assert snap.downloaded == 1
    assert snap.total == 1


def test_network_abort_retries_and_recovers(
    tmp_path, sync_store, fake_server, account
) -> None:
    seed_account(fake_server)
    seed_folder(fake_server, "INBOX", [_msg(1), _msg(2)])
    fake_server.abort_once_uids.add(1)  # first fetch of uid 1 dies mid-flight
    snap = _engine(
        tmp_path, account, sync_store, retry_attempts=3
    ).run(account, MODE_BACKFILL)
    assert snap.downloaded == 2
    assert fake_server.abort_fetch_count >= 1


def test_failed_records_are_retried_next_run(
    tmp_path, sync_store, fake_server, account
) -> None:
    seed_account(fake_server)
    seed_folder(fake_server, "INBOX", [_msg(1), _msg(2)])
    fake_server.reject_fetch_uids.add(2)  # part fetch for uid 2 gets NO

    _engine(tmp_path, account, sync_store).run(account, MODE_BACKFILL)
    counts = sync_store.count_by_status(account.account_id)
    failedish = counts.get(STATUS_FAILED, 0) + counts.get(
        "server_unavailable", 0
    )
    assert failedish == 1

    fake_server.reject_fetch_uids.clear()
    snap = _engine(tmp_path, account, sync_store).run(
        account, MODE_INCREMENTAL
    )
    assert snap.downloaded == 1
    counts = sync_store.count_by_status(account.account_id)
    assert counts.get(STATUS_DONE, 0) == 2


def test_filters_limit_downloads(
    tmp_path, sync_store, fake_server, account
) -> None:
    seed_account(fake_server)
    seed_folder(
        fake_server, "INBOX", [_msg(1, subject="发票"), _msg(2, subject="广告")]
    )
    account.filters.subject_keywords = ["发票"]
    snap = _engine(tmp_path, account, sync_store).run(account, MODE_BACKFILL)
    assert snap.downloaded == 1


def test_account_id_isolation(
    tmp_path, sync_store, fake_server, account
) -> None:
    seed_account(fake_server)
    seed_folder(fake_server, "INBOX", [_msg(1)])
    _engine(tmp_path, account, sync_store).run(account, MODE_BACKFILL)
    assert sync_store.count_by_status("other-acc") == {}
    assert sync_store.count_by_status(account.account_id)[STATUS_DONE] == 1


def test_pause_blocks_until_released(
    tmp_path, sync_store, fake_server, account
) -> None:
    seed_account(fake_server)
    seed_folder(fake_server, "INBOX", [_msg(1), _msg(2)])
    pause = threading.Event()
    engine = MailSyncEngine(
        store=sync_store,
        invoice_root=tmp_path,
        pending_dir_name="pending",
        raw_dir_name="raw",
        cancel_event=threading.Event(),
        pause_event=pause,
        options=EngineOptions(batch_size=1),
        secret_getter=lambda _a: "auth-code-1",
    )
    original = engine._download_candidate
    calls = []

    def pause_after_first(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            pause.set()
        return original(*args, **kwargs)

    engine._download_candidate = pause_after_first  # type: ignore[assignment]
    holder: dict = {}

    def runner():
        holder["snap"] = engine.run(account, MODE_BACKFILL)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    import time as _t

    deadline = _t.time() + 5
    while _t.time() < deadline and not engine.snapshot.paused:
        _t.sleep(0.05)
    assert engine.snapshot.paused
    pause.clear()
    thread.join(timeout=10)
    assert holder["snap"].downloaded == 2


def test_base64_body_decoded_to_real_pdf_bytes(
    tmp_path, sync_store, fake_server, account
) -> None:
    """Live bug: NetEase returns BODY[n] still base64-encoded. The stored
    file must contain decoded PDF bytes, not the base64 text."""
    seed_account(fake_server)
    seed_folder(fake_server, "INBOX", [_msg(1, "发票.pdf", VALID_PDF)])
    snap = _engine(tmp_path, account, sync_store).run(account, MODE_BACKFILL)
    assert snap.downloaded == 1
    raw_files = list((tmp_path / "raw").rglob("*.pdf"))
    assert len(raw_files) == 1
    assert raw_files[0].read_bytes() == VALID_PDF


def test_literal_filename_end_to_end(
    tmp_path, sync_store, fake_server, account
) -> None:
    """Live bug: {n} literal filename params produced names like '{266}...'
    without a .pdf suffix — unreadable by the invoice scanner."""
    seed_account(fake_server)
    message = FakeMessage(
        uid=7,
        message_id="lit@x",
        attachments=[
            FakeAttachment(
                "招商银行掌上生活-信用卡电子账单.pdf",
                "application/pdf",
                VALID_PDF,
                literal_filename=True,
            )
        ],
    )
    seed_folder(fake_server, "INBOX", [message])
    snap = _engine(tmp_path, account, sync_store).run(account, MODE_BACKFILL)
    assert snap.downloaded == 1
    pending = list((tmp_path / "pending").glob("*.pdf"))
    assert len(pending) == 1
    assert "招商银行掌上生活-信用卡电子账单" in pending[0].name
    assert "{29}" not in pending[0].name and "{" not in pending[0].name
    assert pending[0].read_bytes() == VALID_PDF


def test_snapshot_reports_server_folder_counts(
    tmp_path, sync_store, fake_server, account
) -> None:
    seed_account(fake_server)
    folder = seed_folder(fake_server, "INBOX", [_msg(1), _msg(2)])
    folder.unseen = 1
    snap = _engine(tmp_path, account, sync_store).run(account, MODE_BACKFILL)
    assert snap.folder_exists == 2
    assert snap.folder_unseen == 1
    assert snap.total == 2  # this run, not the cumulative DB total


def test_corrupt_done_record_redownloads_via_retry(
    tmp_path, sync_store, fake_server, account
) -> None:
    """Live repair path: a 'done' record whose file holds base64 text and a
    {n}-corrupted name gets re-downloaded with the real name + bytes once it
    is marked failed (service repair does the marking)."""
    seed_account(fake_server)
    message = FakeMessage(
        uid=5,
        message_id="re@x",
        attachments=[
            FakeAttachment("电子发票-差旅报销.pdf", "application/pdf", VALID_PDF)
        ],
    )
    folder = seed_folder(fake_server, "INBOX", [message])

    corrupt = tmp_path / "raw" / "u5_a0_{266}招商银行掌上生活-信用"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_bytes(b"JVBERi0xLjQKMSAwIG9iago8PD4KZW5kb2JqCnRyYWlsZXIKJSVFT0YK")

    db_folder = sync_store.upsert_folder(account.account_id, "INBOX")
    sync_store.update_folder_state(
        db_folder.id, uidvalidity=1001, last_seen_uid=5
    )
    record = sync_store.upsert_attachment(
        account_id=account.account_id,
        folder_id=db_folder.id,
        uidvalidity=1001,
        uid=5,
        message_id="re@x",
        subject="s",
        sender="a@x.com",
        message_date="",
        attachment_index=0,
        attachment_name="{266}招商银行掌上生活-信用",
        part_number="2",
        size=100,
    )
    sync_store.mark_attachment(
        record.id, STATUS_DONE, local_path=str(corrupt), content_hash="x"
    )
    # Service repair marks the corrupt file for re-download.
    sync_store.mark_attachment(
        record.id,
        STATUS_FAILED,
        last_error="本地文件内容无效，待重新下载",
        last_error_code="INVALID_PDF",
    )

    snap = _engine(tmp_path, account, sync_store).run(
        account, MODE_INCREMENTAL
    )
    assert snap.downloaded == 1
    updated = sync_store.get_attachment(record.id)
    assert updated.download_status == STATUS_DONE
    assert updated.attachment_name == "电子发票-差旅报销.pdf"
    stored = Path(updated.local_path)
    assert stored.read_bytes() == VALID_PDF
    assert stored.name.endswith(".pdf")
    # Original corrupt file was left untouched.
    assert corrupt.read_bytes().startswith(b"JVBER")
    pending = list((tmp_path / "pending").glob("*.pdf"))
    assert len(pending) == 1
    assert pending[0].read_bytes() == VALID_PDF
