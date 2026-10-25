"""Tests for the IMAP modified UTF-7 codec."""

from __future__ import annotations

from mail.utf7 import decode_imap_utf7, encode_imap_utf7


def test_ascii_passthrough() -> None:
    assert decode_imap_utf7("INBOX") == "INBOX"
    assert encode_imap_utf7("INBOX") == "INBOX"


def test_ampersand_escaping() -> None:
    assert decode_imap_utf7("R&D") == "R&D"
    assert encode_imap_utf7("R&D") == "R&-D"
    assert decode_imap_utf7(encode_imap_utf7("R&D")) == "R&D"


def test_chinese_roundtrip() -> None:
    for name in ["收件箱", "发票文件夹", "已发送邮件", "草稿箱", "INBOX.账单 2026"]:
        assert decode_imap_utf7(encode_imap_utf7(name)) == name


def test_mixed_ascii_and_chinese_roundtrip() -> None:
    name = "Receipts 发票 & 收据"
    assert decode_imap_utf7(encode_imap_utf7(name)) == name


def test_known_vector() -> None:
    # RFC 3501 example-ish: &Jjo! style encoding of U+263A would be &Jjo-
    assert decode_imap_utf7("&Jjo-") == "☺"


def test_truncated_sequence_is_literal() -> None:
    assert decode_imap_utf7("foo&") == "foo&"
