"""Attachment and message filtering against user-configured rules."""

from __future__ import annotations

from mail.models import AttachmentPart, MailFilterConfig, MessageInfo


def message_matches(message: MessageInfo, filters: MailFilterConfig) -> bool:
    """Apply sender and subject-keyword rules to a message.

    Both lists act as "any of" allow-lists; empty lists match everything.
    Matching is case-insensitive substring matching on raw header text.
    """
    if filters.senders:
        sender_text = message.sender.casefold()
        if not any(s.casefold() in sender_text for s in filters.senders if s.strip()):
            return False
    if filters.subject_keywords:
        subject_text = message.subject.casefold()
        if not any(
            kw.casefold() in subject_text for kw in filters.subject_keywords if kw.strip()
        ):
            return False
    return True


def attachment_matches(part: AttachmentPart, filters: MailFilterConfig) -> bool:
    """Apply extension/name/size rules to an attachment candidate."""
    extensions = filters.normalized_extensions()
    if extensions:
        suffix_ok = any(
            part.filename.casefold().endswith(ext) for ext in extensions
        )
        # A declared PDF content type counts as matching the ".pdf" rule.
        type_ok = (
            ".pdf" in extensions
            and part.content_type in {"APPLICATION/PDF", "APPLICATION/X-PDF"}
        )
        if not (suffix_ok or type_ok):
            return False
    if filters.attachment_name_keywords:
        name_text = part.filename.casefold()
        if not any(
            kw.casefold() in name_text
            for kw in filters.attachment_name_keywords
            if kw.strip()
        ):
            return False
    return True


def attachment_too_large(part: AttachmentPart, filters: MailFilterConfig) -> bool:
    """Guardrail against malicious or absurd attachment sizes."""
    limit_mb = filters.max_attachment_mb
    if limit_mb <= 0:
        return False
    return part.size > limit_mb * 1024 * 1024
