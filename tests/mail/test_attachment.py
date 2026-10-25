"""Tests for BODYSTRUCTURE parsing and attachment decoding."""

from __future__ import annotations

from mail.attachment import (
    decode_attachment_name,
    decode_mime_words,
    extract_attachments,
    is_pdf_candidate,
    looks_like_pdf_bytes,
)


def _text_part() -> list:
    return ["TEXT", "PLAIN", ["CHARSET", "UTF-8"], None, None, "7BIT", 10, 1, None, None, None, None]


def _pdf_part(name: str, size: int = 5000, disposition="ATTACHMENT") -> list:
    return [
        "APPLICATION", "PDF",
        ["NAME", name],
        None, None, "BASE64", size, None,
        [disposition, ["FILENAME", name]],
        None, None,
    ]


def _multipart(*parts) -> list:
    return [list(p) for p in parts] + ["MIXED"]


def test_extract_simple_attachment() -> None:
    tree = _multipart(_text_part(), _pdf_part("发票.pdf"))
    parts = extract_attachments(tree)
    assert len(parts) == 1
    assert parts[0].filename == "发票.pdf"
    assert parts[0].part_number == "2"
    assert parts[0].content_type == "APPLICATION/PDF"


def test_extract_inline_part_with_filename() -> None:
    tree = _multipart(_text_part(), _pdf_part("receipt.pdf", disposition="INLINE"))
    parts = extract_attachments(tree)
    assert len(parts) == 1
    assert parts[0].is_inline_with_name is True


def test_part_without_name_is_skipped() -> None:
    unnamed = ["IMAGE", "PNG", None, None, None, "BASE64", 999, None, None, None, None]
    tree = _multipart(_text_part(), unnamed)
    assert extract_attachments(tree) == []


def test_nested_multipart() -> None:
    inner = _multipart(_text_part(), _pdf_part("inner.pdf"))
    tree = _multipart(inner, _pdf_part("outer.pdf"))
    parts = extract_attachments(tree)
    names = {p.filename for p in parts}
    assert names == {"inner.pdf", "outer.pdf"}


def test_rfc2231_continued_filename() -> None:
    params = {
        "NAME*0": "Very",
        "NAME*1": "LongName.pdf",
    }
    assert decode_attachment_name(params, {}) == "VeryLongName.pdf"


def test_rfc2231_extended_filename() -> None:
    encoded = "utf-8''%E5%8F%91%E7%A5%A8.pdf"
    params = {"NAME*": encoded}
    assert decode_attachment_name(params, {}) == "发票.pdf"


def test_encoded_word_filename() -> None:
    value = "=?gb18030?b?v9fI19DC?="  # not a real word; decode should not crash
    result = decode_mime_words(value)
    assert isinstance(result, str)


def test_pdf_candidate_by_content_type() -> None:
    part = extract_attachments(
        _multipart(_text_part(), _pdf_part("noext"))
    )[0]
    assert is_pdf_candidate(part)


def test_pdf_candidate_by_extension_octet_stream() -> None:
    node = [
        "APPLICATION", "OCTET-STREAM",
        ["NAME", "bill.PDF"],
        None, None, "BASE64", 100, None,
        ["ATTACHMENT", ["FILENAME", "bill.PDF"]],
        None, None,
    ]
    part = extract_attachments(_multipart(_text_part(), node))[0]
    assert is_pdf_candidate(part)


def test_pdf_bytes_validation() -> None:
    good = b"%PDF-1.4\nbody\n%%EOF"
    assert looks_like_pdf_bytes(good)
    assert not looks_like_pdf_bytes(b"not a pdf")
    assert not looks_like_pdf_bytes(b"%PDF-1.4 missing trailer")
    assert not looks_like_pdf_bytes(b"")
