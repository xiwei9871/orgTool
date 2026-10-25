"""Attachment persistence: atomic writes, PDF validation, pending import."""

from __future__ import annotations

import email.utils
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from pathlib import Path

from core.conflict_resolver import resolve_conflict_path
from mail.attachment import looks_like_pdf_bytes
from mail.errors import MailErrorCode, MailSyncError
from mail.filenames import safe_join, sanitize_filename
from mail.models import MessageInfo


@dataclass(slots=True)
class WrittenAttachment:
    """The result of a verified attachment write."""

    path: Path
    sha256: str
    size: int


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write_bytes(target: Path, data: bytes) -> Path:
    """Write ``data`` to ``target`` via a same-directory temp file + replace.

    A ``.part`` temp file is written, flushed, and atomically renamed so a
    crash can never leave a half-written file at the final path.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".part")
    try:
        with temp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    except OSError as exc:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise MailSyncError(
            MailErrorCode.FILE_WRITE_FAILED,
            f"写入附件失败: {target.name}",
            detail=str(exc),
        ) from exc
    return target


def mask_email(value: str) -> str:
    """Mask an email address for UI/log display (``t***@163.com``)."""
    local, sep, domain = value.partition("@")
    if not sep:
        return value[:1] + "***" if value else ""
    if len(local) <= 1:
        return f"{local}***@{domain}"
    return f"{local[0]}***@{domain}"


def sanitize_subject_folder(value: str) -> str:
    """Make a short safe directory fragment from an account label."""
    cleaned = re.sub(r"\s+", "", value.strip())
    return sanitize_filename(cleaned, fallback="account")


def build_raw_dir(
    invoice_root: Path,
    raw_dir_name: str,
    account_label: str,
    month_key: str = "",
) -> Path:
    """Resolve the raw-attachment directory for an account and month."""
    parts = [sanitize_subject_folder(account_label)]
    if month_key:
        parts.append(sanitize_filename(month_key, fallback="unknown-month"))
    return safe_join(invoice_root, raw_dir_name, *parts)


def write_verified_pdf(
    raw_dir: Path,
    filename: str,
    data: bytes,
    require_pdf: bool = True,
) -> WrittenAttachment:
    """Validate and atomically store one attachment payload.

    PDF validation checks the ``%PDF-`` magic header and ``%%EOF`` trailer;
    a candidate that fails is rejected with ``INVALID_PDF`` rather than
    being trusted based on filename alone.
    """
    if require_pdf and not looks_like_pdf_bytes(data):
        raise MailSyncError(
            MailErrorCode.INVALID_PDF,
            "附件内容不是有效的 PDF（头部/尾部校验失败）",
            detail=filename,
        )
    safe_name = sanitize_filename(filename)
    target = resolve_conflict_path(safe_join(raw_dir, safe_name))
    atomic_write_bytes(target, data)
    return WrittenAttachment(path=target, sha256=sha256_bytes(data), size=len(data))


def month_key_from_date(message_date: str) -> str:
    """Best-effort ``YYYYMM`` extraction from a mail date header."""
    value = (message_date or "").strip()
    if not value:
        return ""
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed is not None:
            return f"{parsed.year}{parsed.month:02d}"
    except (TypeError, ValueError):
        pass
    match = re.search(r"(\d{4})[-/.](\d{1,2})", value)
    if match:
        return f"{match.group(1)}{int(match.group(2)):02d}"
    match = re.search(r"(\d{4})年\s*(\d{1,2})月", value)
    if match:
        return f"{match.group(1)}{int(match.group(2)):02d}"
    return ""


def write_source_sidecar(
    pending_pdf: Path,
    source: dict,
) -> Path:
    """Write ``<file>.source.json`` recording mail provenance."""
    sidecar = pending_pdf.with_name(pending_pdf.name + ".source.json")
    sidecar.write_text(
        json.dumps(source, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return sidecar


def load_source_sidecar(pdf_path: Path) -> dict | None:
    """Read a ``.source.json`` sidecar if it exists next to a PDF."""
    sidecar = pdf_path.with_name(pdf_path.name + ".source.json")
    if not sidecar.is_file():
        return None
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def remove_source_sidecar(pdf_path: Path) -> None:
    pdf_path.with_name(pdf_path.name + ".source.json").unlink(missing_ok=True)


def build_source_info(
    account_label: str,
    account_email: str,
    folder_name: str,
    uid: int,
    message: MessageInfo,
    attachment_name: str,
    sha256: str,
    downloaded_at: str,
) -> dict:
    """Assemble provenance metadata for one imported attachment."""
    return {
        "account_label": account_label,
        "account_email": mask_email(account_email),
        "folder": folder_name,
        "uid": uid,
        "message_id": message.message_id,
        "subject": message.subject,
        "sender": message.sender,
        "message_date": message.date,
        "attachment_name": attachment_name,
        "sha256": sha256,
        "downloaded_at": downloaded_at,
    }
