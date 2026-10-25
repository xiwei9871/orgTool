"""MIME BODYSTRUCTURE parsing and attachment filename decoding."""

from __future__ import annotations

import email.header
import email.utils
import re
from collections.abc import Iterable

from mail.models import AttachmentPart

PDF_MAGIC = b"%PDF-"
PDF_TRAILER = b"%%EOF"
PDF_SNIFF_BYTES = 1024


def _params_to_dict(params: object) -> dict[str, str]:
    """Convert a BODYSTRUCTURE parameter list into a case-insensitive dict."""
    result: dict[str, str] = {}
    if not isinstance(params, list):
        return result
    for index in range(0, len(params) - 1, 2):
        key = params[index]
        value = params[index + 1]
        if isinstance(key, str) and isinstance(value, str):
            result[key.upper()] = value
    return result


def _is_single_part(node: object) -> bool:
    return (
        isinstance(node, list)
        and len(node) >= 2
        and isinstance(node[0], str)
        and isinstance(node[1], str)
    )


def _iter_parts(node: object, prefix: str = "") -> Iterable[tuple[str, list]]:
    """Yield (part_number, part_node) for every leaf MIME part."""
    if not isinstance(node, list):
        return
    index = 0
    child_index = 0
    while index < len(node) and isinstance(node[index], list):
        child = node[index]
        child_index += 1
        number = f"{prefix}{child_index}"
        if _is_single_part(child):
            yield number, child
        else:
            yield from _iter_parts(child, f"{number}.")
        index += 1


def _find_disposition(part: list) -> tuple[str, dict[str, str]]:
    """Locate the (disposition, params) extension data of a part."""
    for element in part[7:]:
        if (
            isinstance(element, list)
            and len(element) >= 1
            and isinstance(element[0], str)
            and element[0].upper() in {"ATTACHMENT", "INLINE"}
        ):
            params = _params_to_dict(element[1]) if len(element) > 1 else {}
            return element[0].upper(), params
    return "", {}


def _collect_continuations(
    params: dict[str, str], base: str
) -> list[tuple[int, str, bool]]:
    """Collect RFC 2231 continuation segments like name*0* / name*1."""
    segments: list[tuple[int, str, bool]] = []
    pattern = re.compile(rf"^{re.escape(base)}\*(\d+)\*?$")
    for key, value in params.items():
        match = pattern.match(key)
        if match:
            segments.append((int(match.group(1)), value, key.endswith("*")))
    segments.sort(key=lambda item: item[0])
    return segments


def _decode_rfc2231_value(value: str) -> str:
    """Decode an extended parameter value ``charset'lang'encoded``."""
    if "'" not in value:
        return _percent_unquote(value, "utf-8")
    try:
        charset, _lang, encoded = value.split("'", 2)
    except ValueError:
        return _percent_unquote(value, "utf-8")
    charset = charset or "utf-8"
    return _percent_unquote(encoded, charset)


def _percent_unquote(value: str, charset: str) -> str:
    raw = bytearray()
    index = 0
    while index < len(value):
        char = value[index]
        if char == "%" and index + 2 < len(value):
            try:
                raw.append(int(value[index + 1 : index + 3], 16))
                index += 3
                continue
            except (ValueError, IndexError):
                pass
        raw.extend(char.encode("utf-8", errors="replace"))
        index += 1
    try:
        return bytes(raw).decode(charset, errors="replace")
    except LookupError:
        return bytes(raw).decode("utf-8", errors="replace")


def decode_mime_words(value: str) -> str:
    """Decode RFC 2047 encoded words such as =?gb18030?b?...?="""
    if "=?" not in value:
        return value
    try:
        fragments = email.header.decode_header(value)
        return str(email.header.make_header(fragments))
    except (email.errors.HeaderParseError, LookupError, ValueError):
        return value


def decode_attachment_name(
    params: dict[str, str], disposition_params: dict[str, str]
) -> str:
    """Resolve the best filename for an attachment part.

    Handles plain ``name``/``filename``, RFC 2231 ``name*``/``filename*``
    (including continuations), and RFC 2047 encoded words.
    """
    for base, source in (
        ("FILENAME", disposition_params),
        ("NAME", params),
    ):
        starred = source.get(f"{base}*")
        if starred:
            return decode_mime_words(_decode_rfc2231_value(starred)).strip()
        segments = _collect_continuations(source, base)
        if segments:
            combined = "".join(segment for _, segment, _ in segments)
            if any(encoded for _, _, encoded in segments):
                return decode_mime_words(_decode_rfc2231_value(combined)).strip()
            return decode_mime_words(combined).strip()
        plain = source.get(base)
        if plain:
            return decode_mime_words(plain).strip()
    return ""


def extract_attachments(bodystructure: object) -> list[AttachmentPart]:
    """Walk a parsed BODYSTRUCTURE tree and return attachment parts.

    A part counts as an attachment when it has
    ``Content-Disposition: attachment`` or carries a filename (including
    inline parts with a name — e.g. inline PDF invoices).
    """
    attachments: list[AttachmentPart] = []
    for part_number, node in _iter_parts(bodystructure):
        content_type = f"{node[0]}/{node[1]}".upper()
        params = _params_to_dict(node[2] if len(node) > 2 else None)
        try:
            size = int(node[6]) if len(node) > 6 and node[6] is not None else 0
        except (TypeError, ValueError):
            size = 0
        disposition, disp_params = _find_disposition(node)
        filename = decode_attachment_name(params, disp_params)
        is_attachment = disposition == "ATTACHMENT" or bool(filename)
        if not is_attachment:
            continue
        attachments.append(
            AttachmentPart(
                index=len(attachments),
                part_number=part_number,
                filename=filename,
                content_type=content_type,
                size=size,
                is_inline_with_name=(disposition == "INLINE" and bool(filename)),
            )
        )
    return attachments


def looks_like_pdf_bytes(data: bytes) -> bool:
    """Verify PDF content by magic header and EOF trailer."""
    if len(data) < 8:
        return False
    head = data[:PDF_SNIFF_BYTES]
    if PDF_MAGIC not in head:
        return False
    tail = data[-PDF_SNIFF_BYTES:]
    return PDF_TRAILER in tail


def is_pdf_candidate(part: AttachmentPart) -> bool:
    """Decide from structure metadata whether a part may be a PDF."""
    if part.filename.casefold().endswith(".pdf"):
        return True
    return part.content_type in {"APPLICATION/PDF", "APPLICATION/X-PDF"}
