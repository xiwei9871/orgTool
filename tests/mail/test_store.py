"""Tests for the SQLite sync-state store."""

from __future__ import annotations

from mail.store import (
    STATUS_DONE,
    STATUS_DOWNLOADING,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_SKIPPED_DUPLICATE,
    MailSyncStore,
)


def _attach(store: MailSyncStore, uid: int = 1, index: int = 0, status=None):
    record = store.upsert_attachment(
        account_id="acc1",
        folder_id=1,
        uidvalidity=1001,
        uid=uid,
        message_id=f"m{uid}@x",
        subject="s",
        sender="a@b",
        message_date="Mon, 05 Jan 2026",
        attachment_index=index,
        attachment_name=f"f{uid}_{index}.pdf",
        part_number="2",
        size=100,
    )
    if status:
        store.mark_attachment(record.id, status)
    return record


def test_upsert_attachment_is_idempotent(sync_store) -> None:
    first = _attach(sync_store, uid=7)
    sync_store.mark_attachment(
        first.id, STATUS_DONE, local_path="/tmp/x.pdf", content_hash="abc"
    )
    again = sync_store.upsert_attachment(
        account_id="acc1",
        folder_id=1,
        uidvalidity=1001,
        uid=7,
        message_id="m7@x",
        subject="s",
        sender="a@b",
        message_date="d",
        attachment_index=0,
        attachment_name="f7_0.pdf",
        part_number="2",
        size=100,
    )
    assert again.id == first.id
    assert again.download_status == STATUS_DONE
    assert again.local_path == "/tmp/x.pdf"


def test_same_uid_different_folders_are_distinct(sync_store) -> None:
    a = _attach(sync_store, uid=5)
    b = sync_store.upsert_attachment(
        account_id="acc1", folder_id=2, uidvalidity=1001, uid=5,
        message_id="m5@x", subject="s", sender="a@b", message_date="d",
        attachment_index=0, attachment_name="f.pdf", part_number="2", size=100,
    )
    assert a.id != b.id


def test_same_message_same_name_attachments_are_distinct(sync_store) -> None:
    a = _attach(sync_store, uid=5, index=0)
    b = _attach(sync_store, uid=5, index=1)
    assert a.id != b.id


def test_uidvalidity_separates_records(sync_store) -> None:
    a = _attach(sync_store, uid=5)
    b = sync_store.upsert_attachment(
        account_id="acc1", folder_id=1, uidvalidity=2002, uid=5,
        message_id="m5@x", subject="s", sender="a@b", message_date="d",
        attachment_index=0, attachment_name="f.pdf", part_number="2", size=100,
    )
    assert a.id != b.id


def test_find_by_hash_dedup(sync_store) -> None:
    record = _attach(sync_store, uid=3)
    sync_store.mark_attachment(
        record.id, STATUS_DONE, local_path="/p/a.pdf", content_hash="deadbeef"
    )
    found = sync_store.find_by_hash("deadbeef")
    assert found is not None and found.id == record.id
    assert sync_store.find_by_hash("deadbeef", exclude_id=record.id) is None
    assert sync_store.find_by_hash("other") is None


def test_pending_and_reset_downloading(sync_store) -> None:
    _attach(sync_store, uid=1)
    r2 = _attach(sync_store, uid=2)
    sync_store.mark_attachment(r2.id, STATUS_DOWNLOADING)
    pending = sync_store.pending_for_folder("acc1", 1, 1001)
    assert len(pending) == 2
    assert sync_store.reset_downloading("acc1") == 1
    record = sync_store.get_attachment(r2.id)
    assert record.download_status == STATUS_PENDING


def test_retryable_failures(sync_store) -> None:
    r1 = _attach(sync_store, uid=1)
    sync_store.mark_attachment(r1.id, STATUS_FAILED, increment_attempts=True)
    r2 = _attach(sync_store, uid=2)
    for _ in range(5):
        sync_store.mark_attachment(r2.id, STATUS_FAILED, increment_attempts=True)
    retryable = sync_store.retryable_failures("acc1", max_attempts=3)
    assert [r.id for r in retryable] == [r1.id]


def test_folder_state(sync_store) -> None:
    folder = sync_store.upsert_folder("acc1", "INBOX")
    sync_store.update_folder_state(folder.id, uidvalidity=4242, last_seen_uid=77)
    updated = sync_store.get_folder("acc1", "INBOX")
    assert updated.uidvalidity == 4242
    assert updated.last_seen_uid == 77


def test_task_lifecycle(sync_store) -> None:
    task_id = sync_store.create_task(
        "acc1", 1, "INBOX", "backfill", since_date="2026-01-01"
    )
    sync_store.update_task(task_id, total=10, cursor_uid=42)
    task = sync_store.get_task(task_id)
    assert task["total"] == 10 and task["cursor_uid"] == 42
    assert sync_store.unfinished_tasks("acc1")[0]["id"] == task_id
    sync_store.update_task(task_id, status="done")
    assert sync_store.unfinished_tasks("acc1") == []


def test_backup_and_integrity(sync_store, tmp_path) -> None:
    _attach(sync_store, uid=9)
    backup = sync_store.backup_to(tmp_path / "backup.db")
    assert backup.exists()
    assert sync_store.check_integrity()


def test_count_by_status(sync_store) -> None:
    _attach(sync_store, uid=1)
    r2 = _attach(sync_store, uid=2)
    sync_store.mark_attachment(r2.id, STATUS_SKIPPED_DUPLICATE)
    counts = sync_store.count_by_status("acc1")
    assert counts[STATUS_PENDING] == 1
    assert counts[STATUS_SKIPPED_DUPLICATE] == 1
