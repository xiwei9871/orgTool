"""Tests for atomic writes, sidecars, and directory layout."""

from __future__ import annotations

from mail.importer import (
    atomic_write_bytes,
    build_raw_dir,
    build_source_info,
    load_source_sidecar,
    mask_email,
    month_key_from_date,
    write_source_sidecar,
    write_verified_pdf,
)
from mail.models import MessageInfo
from tests.mail.conftest import VALID_PDF


def test_atomic_write_creates_parent_dirs(tmp_path) -> None:
    target = tmp_path / "a" / "b" / "file.pdf"
    result = atomic_write_bytes(target, b"data")
    assert result.read_bytes() == b"data"
    assert not (tmp_path / "a" / "b" / "file.pdf.part").exists()


def test_write_verified_pdf_rejects_bad_content(tmp_path) -> None:
    import pytest

    from mail.errors import MailSyncError

    with pytest.raises(MailSyncError):
        write_verified_pdf(tmp_path, "fake.pdf", b"not a pdf")


def test_write_verified_pdf_conflict_names(tmp_path) -> None:
    first = write_verified_pdf(tmp_path, "账单.pdf", VALID_PDF)
    second_data = b"%PDF-1.4\nsecond\n%%EOF"
    second = write_verified_pdf(tmp_path, "账单.pdf", second_data)
    assert first.path != second.path
    assert first.path.exists() and second.path.exists()


def test_source_sidecar_roundtrip_and_masking(tmp_path) -> None:
    target = tmp_path / "bill.pdf"
    atomic_write_bytes(target, VALID_PDF)
    message = MessageInfo(
        uid=5,
        message_id="m5@x",
        subject="发票",
        sender="shop@x.com",
        date="Mon, 05 Jan 2026 10:00:00 +0800",
    )
    source = build_source_info(
        account_label="我的163",
        account_email="realname@163.com",
        folder_name="INBOX",
        uid=5,
        message=message,
        attachment_name="bill.pdf",
        sha256="abc",
        downloaded_at="2026-01-05T11:00:00",
    )
    write_source_sidecar(target, source)
    loaded = load_source_sidecar(target)
    assert loaded["uid"] == 5
    assert loaded["subject"] == "发票"
    # Email is masked in the sidecar, not stored in clear.
    assert loaded["account_email"] == "r***@163.com"


def test_load_source_sidecar_missing(tmp_path) -> None:
    assert load_source_sidecar(tmp_path / "none.pdf") is None


def test_build_raw_dir_layout_and_traversal(tmp_path) -> None:
    raw = build_raw_dir(tmp_path, "raw", "我的 163", "202601")
    assert raw.parent.parent == tmp_path / "raw"
    # Traversal fragments are sanitized away; the result must stay in root.
    sneaky = build_raw_dir(tmp_path, "raw", "..\\..\\evil", "202601")
    assert str(sneaky).startswith(str((tmp_path / "raw").resolve()))
    # A crafted raw_dir_name that escapes must raise.
    import pytest

    with pytest.raises(ValueError):
        build_raw_dir(tmp_path, "..", "account", "202601")


def test_month_key_from_date() -> None:
    assert month_key_from_date("Mon, 05 Jan 2026 10:00:00 +0800") == "202601"
    assert month_key_from_date("2026-02-01") == "202602"
    assert month_key_from_date("") == ""


def test_mask_email() -> None:
    assert mask_email("realname@163.com") == "r***@163.com"
    assert mask_email("a@b.com") == "a***@b.com"
    assert mask_email("noat") == "n***"
