"""Tests for filename sanitization and path traversal protection."""

from __future__ import annotations

import pytest

from mail.filenames import safe_join, sanitize_filename


def test_sanitize_strips_traversal() -> None:
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("..\\..\\evil.pdf") == "evil.pdf"
    assert sanitize_filename("..") == "attachment"


def test_sanitize_removes_invalid_chars() -> None:
    cleaned = sanitize_filename('inv<>oice:"/\\|?*.pdf')
    assert "<" not in cleaned and ":" not in cleaned and "|" not in cleaned
    assert cleaned.endswith(".pdf")


def test_sanitize_keeps_chinese_and_spaces() -> None:
    assert sanitize_filename("京东 发票 2026-01.pdf") == "京东 发票 2026-01.pdf"


def test_sanitize_reserved_names() -> None:
    assert sanitize_filename("CON.pdf") != "CON.pdf"
    assert sanitize_filename("con.pdf").startswith("_")
    assert sanitize_filename("aux.txt").startswith("_")


def test_sanitize_empty_and_dots() -> None:
    assert sanitize_filename("") == "attachment"
    assert sanitize_filename("...") == "attachment"
    assert sanitize_filename("   ") == "attachment"


def test_sanitize_truncates_long_names() -> None:
    long_name = "发票" * 200 + ".pdf"
    cleaned = sanitize_filename(long_name)
    assert len(cleaned.encode("utf-8")) <= 200
    assert cleaned.endswith(".pdf") or ".pdf" not in cleaned  # may cut suffix


def test_safe_join_inside_root(tmp_path) -> None:
    root = tmp_path / "root"
    result = safe_join(root, "a", "b.pdf")
    assert str(result).startswith(str(root.resolve()))


def test_safe_join_rejects_traversal(tmp_path) -> None:
    root = tmp_path / "root"
    with pytest.raises(ValueError):
        safe_join(root, "..", "..", "outside")
    with pytest.raises(ValueError):
        safe_join(root, "/absolute/path")
