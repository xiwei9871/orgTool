"""IMAP modified UTF-7 codec (RFC 3501 section 5.1.3)."""

from __future__ import annotations

import base64


def decode_imap_utf7(value: str) -> str:
    """Decode a modified UTF-7 mailbox name to plain text."""
    result: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char != "&":
            result.append(char)
            index += 1
            continue
        end = value.find("-", index)
        if end == -1:
            # Truncated shift: treat remainder literally.
            result.append(value[index:])
            break
        token = value[index + 1 : end]
        if token == "":
            result.append("&")
        else:
            b64 = token.replace(",", "/")
            padding = "=" * (-len(b64) % 4)
            try:
                decoded = base64.b64decode(b64 + padding).decode("utf-16-be")
            except (ValueError, UnicodeDecodeError):
                decoded = value[index : end + 1]
            result.append(decoded)
        index = end + 1
    return "".join(result)


def encode_imap_utf7(value: str) -> str:
    """Encode a mailbox name into modified UTF-7 for IMAP commands."""
    result: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        raw = "".join(buffer).encode("utf-16-be")
        token = base64.b64encode(raw).decode("ascii").rstrip("=").replace("/", ",")
        result.append("&" + token + "-")
        buffer.clear()

    for char in value:
        code = ord(char)
        if char == "&":
            flush()
            result.append("&-")
        elif 0x20 <= code <= 0x7E:
            flush()
            result.append(char)
        else:
            buffer.append(char)
    flush()
    return "".join(result)
