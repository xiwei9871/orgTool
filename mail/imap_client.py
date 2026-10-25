"""IMAP client wrapper with NetEase compatibility handling.

NetEase 163/126 servers require an RFC 2971 ``ID`` command after login —
servers reject ``SELECT`` for clients that never identified themselves.
This client always sends a genuine client ID (never impersonating another
official client) and exposes staged connection probing so callers can
distinguish authentication failures, ID incompatibilities, folder access
failures, and server-side refusals.
"""

from __future__ import annotations

import imaplib
import re
import socket
import ssl
from dataclasses import dataclass
from datetime import date

from mail.errors import MailErrorCode, MailSyncError
from mail.models import MailFolder
from mail.utf7 import decode_imap_utf7, encode_imap_utf7

_CLIENT_NAME = "orgTool"
_CLIENT_VERSION = "2.0"
_CLIENT_VENDOR = "DesktopSmartOrganizer"

_IMAP_MONTHS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

TRANSIENT_EXCEPTIONS = (
    socket.timeout,
    TimeoutError,
    ConnectionError,
    imaplib.IMAP4.abort,
    ssl.SSLError,
)


@dataclass(slots=True)
class SelectResult:
    """Outcome of selecting a mailbox."""

    exists: int
    uidvalidity: int
    unseen: int = -1
    recent: int = -1


def format_imap_date(value: date) -> str:
    """Format a date for IMAP SINCE/BEFORE search terms."""
    return f"{value.day}-{_IMAP_MONTHS[value.month - 1]}-{value.year}"


class ImapClient:
    """Thin synchronous wrapper around imaplib with staged diagnostics."""

    def __init__(
        self,
        host: str,
        port: int,
        use_ssl: bool = True,
        timeout: float = 30.0,
        client_name: str = _CLIENT_NAME,
        client_version: str = _CLIENT_VERSION,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.use_ssl = use_ssl
        self.timeout = timeout
        self.client_name = client_name
        self.client_version = client_version
        self._conn: imaplib.IMAP4 | imaplib.IMAP4_SSL | None = None
        self.id_supported: bool | None = None
        self._selected: str | None = None

    # ------------------------------------------------------------------
    # Connection lifecycle

    def connect(self) -> None:
        """Open the TCP/TLS connection to the IMAP server."""
        try:
            if self.use_ssl:
                context = ssl.create_default_context()
                self._conn = imaplib.IMAP4_SSL(
                    self.host, self.port, timeout=self.timeout, ssl_context=context
                )
            else:
                self._conn = imaplib.IMAP4(self.host, self.port, timeout=self.timeout)
        except (socket.timeout, TimeoutError) as exc:
            raise MailSyncError(
                MailErrorCode.NETWORK_TIMEOUT, f"连接服务器超时: {self.host}:{self.port}"
            ) from exc
        except (OSError, ssl.SSLError) as exc:
            raise MailSyncError(
                MailErrorCode.NETWORK_TIMEOUT,
                f"无法连接服务器: {self.host}:{self.port}",
                detail=str(exc),
            ) from exc

    def login(self, username: str, secret: str) -> None:
        """Authenticate with the IMAP LOGIN command using an authorization code."""
        if not secret:
            raise MailSyncError(
                MailErrorCode.AUTH_CODE_REQUIRED,
                "需要客户端授权码（不是邮箱登录密码）",
            )
        conn = self._require_conn()
        try:
            conn.login(username, secret)
        except imaplib.IMAP4.error as exc:
            raise MailSyncError(
                MailErrorCode.AUTH_FAILED,
                "登录失败：请确认使用的是客户端授权码而非登录密码",
                detail=_safe_detail(exc),
            ) from exc
        except TRANSIENT_EXCEPTIONS as exc:
            raise MailSyncError(
                MailErrorCode.NETWORK_TIMEOUT, "登录时网络中断", detail=str(exc)
            ) from exc

    def send_id(self) -> bool:
        """Send the RFC 2971 ID command with genuine client information."""
        conn = self._require_conn()
        id_list = (
            f'("name" "{self.client_name}" "version" "{self.client_version}" '
            f'"vendor" "{_CLIENT_VENDOR}")'
        )
        try:
            typ, _ = conn.xatom("ID", id_list)
            self.id_supported = typ == "OK"
        except (imaplib.IMAP4.error, imaplib.IMAP4.abort):
            self.id_supported = False
        return self.id_supported

    def logout(self) -> None:
        """Close the connection gracefully."""
        conn = self._conn
        self._conn = None
        self._selected = None
        if conn is None:
            return
        try:
            conn.close()
        except Exception:
            pass
        try:
            conn.logout()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Folder discovery and selection

    def list_folders(self) -> list[MailFolder]:
        """List all folders, decoding modified UTF-7 names."""
        conn = self._require_conn()
        typ, data = conn.list()
        if typ != "OK":
            raise MailSyncError(
                MailErrorCode.MAILBOX_SELECT_FAILED, "无法列出邮箱文件夹"
            )
        folders: list[MailFolder] = []
        for line in data or []:
            folder = _parse_list_line(line)
            if folder is not None:
                folders.append(folder)
        return folders

    def select_folder(self, name: str) -> SelectResult:
        """Select a folder read-only and return EXISTS/UIDVALIDITY."""
        conn = self._require_conn()
        encoded = encode_imap_utf7(name)
        try:
            typ, data = conn.select(f'"{encoded}"' if " " in encoded else encoded, readonly=True)
        except imaplib.IMAP4.error as exc:
            raise _select_error(name, self.id_supported, exc) from exc
        if typ != "OK":
            raise _select_error(name, self.id_supported, None)
        self._selected = name
        exists = int(data[0]) if data and data[0].isdigit() else 0
        uidvalidity = _response_int(conn.untagged_responses.get("UIDVALIDITY"))
        return SelectResult(exists=exists, uidvalidity=uidvalidity)

    def folder_status(self, name: str) -> dict[str, int]:
        """Return STATUS counters (MESSAGES/UNSEEN/RECENT) for a folder.

        The UNSEEN untagged response during SELECT is a sequence number,
        not a count — STATUS is the reliable way to get unread totals.
        -1 means the server did not provide the value.
        """
        conn = self._require_conn()
        encoded = encode_imap_utf7(name)
        mailbox = f'"{encoded}"' if " " in encoded else encoded
        try:
            typ, data = conn.status(mailbox, "(MESSAGES UNSEEN RECENT)")
        except imaplib.IMAP4.error:
            return {"exists": -1, "unseen": -1, "recent": -1}
        if typ != "OK":
            return {"exists": -1, "unseen": -1, "recent": -1}
        result = {"exists": -1, "unseen": -1, "recent": -1}
        for chunk in data or []:
            text = chunk.decode("utf-8", errors="replace") if isinstance(chunk, bytes) else str(chunk)
            match = re.search(r"MESSAGES\s+(\d+)", text)
            if match:
                result["exists"] = int(match.group(1))
            match = re.search(r"UNSEEN\s+(\d+)", text)
            if match:
                result["unseen"] = int(match.group(1))
            match = re.search(r"RECENT\s+(\d+)", text)
            if match:
                result["recent"] = int(match.group(1))
        return result

    def unselect(self) -> None:
        conn = self._conn
        if conn is not None and self._selected is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._selected = None

    # ------------------------------------------------------------------
    # Message access

    def uid_search(
        self,
        since: date | None = None,
        before: date | None = None,
        uid_min: int | None = None,
    ) -> list[int]:
        """Search for message UIDs matching date/UID criteria."""
        conn = self._require_conn()
        criteria: list[str] = []
        if uid_min is not None:
            criteria += ["UID", f"{uid_min}:*"]
        if since is not None:
            criteria += ["SINCE", format_imap_date(since)]
        if before is not None:
            criteria += ["BEFORE", format_imap_date(before)]
        if not criteria:
            criteria = ["ALL"]
        typ, data = conn.uid("SEARCH", *criteria)
        if typ != "OK":
            raise MailSyncError(
                MailErrorCode.MAILBOX_SELECT_FAILED,
                "邮件搜索失败",
                detail=str(criteria),
            )
        uids: list[int] = []
        for chunk in data or []:
            if isinstance(chunk, bytes):
                uids.extend(int(item) for item in chunk.split() if item.isdigit())
        return sorted(uids)

    def fetch_bodystructure(self, uid: int) -> object:
        """Fetch and parse the BODYSTRUCTURE s-expression for one message."""
        raw = self._fetch_response_text(uid, "(BODYSTRUCTURE)")
        text = raw.decode("utf-8", errors="replace")
        match = re.search(r"BODYSTRUCTURE\s*\(", text)
        if not match:
            raise MailSyncError(
                MailErrorCode.ATTACHMENT_DECODE_FAILED,
                "无法解析邮件结构",
                detail=f"uid={uid}",
            )
        tree, _ = _parse_sexp(text, match.end() - 1)
        return tree

    def fetch_header(self, uid: int) -> bytes:
        """Fetch the message header block."""
        return self._fetch_payload(
            uid, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID SUBJECT FROM DATE)])"
        )

    def fetch_full_message(self, uid: int) -> bytes:
        """Fetch the complete RFC822 message (bounded by callers)."""
        return self._fetch_payload(uid, "(BODY.PEEK[])")

    def fetch_part(self, uid: int, part_number: str) -> bytes:
        """Fetch one MIME part body by BODYSTRUCTURE part number."""
        data = self._fetch_payload(uid, f"(BODY.PEEK[{part_number}])")
        if not data:
            raise MailSyncError(
                MailErrorCode.ATTACHMENT_DECODE_FAILED,
                "附件内容为空或已被服务器删除",
                detail=f"uid={uid} part={part_number}",
            )
        return data

    def capabilities(self) -> set[str]:
        """Return the server capability set."""
        conn = self._require_conn()
        try:
            typ, data = conn.capability()
            if typ == "OK":
                caps: set[str] = set()
                for chunk in data or []:
                    caps.update(
                        item.decode("ascii", errors="replace").upper()
                        for item in chunk.split()
                    )
                return caps
        except imaplib.IMAP4.error:
            pass
        return set()

    # ------------------------------------------------------------------
    # Internal helpers

    def _require_conn(self):
        if self._conn is None:
            raise MailSyncError(MailErrorCode.NETWORK_TIMEOUT, "尚未连接服务器")
        return self._conn

    def _fetch(self, uid: int, spec: str) -> list:
        conn = self._require_conn()
        try:
            typ, data = conn.uid("FETCH", str(uid), spec)
        except TRANSIENT_EXCEPTIONS as exc:
            raise MailSyncError(
                MailErrorCode.NETWORK_TIMEOUT, "读取邮件时网络中断", detail=str(exc)
            ) from exc
        except imaplib.IMAP4.error as exc:
            raise MailSyncError(
                MailErrorCode.ATTACHMENT_DECODE_FAILED,
                "服务器拒绝读取邮件",
                detail=f"uid={uid}: {_safe_detail(exc)}",
            ) from exc
        if typ != "OK":
            raise MailSyncError(
                MailErrorCode.ATTACHMENT_DECODE_FAILED,
                "邮件读取失败",
                detail=f"uid={uid} spec={spec}",
            )
        return data or []

    def _fetch_payload(self, uid: int, spec: str) -> bytes:
        """Return only the literal payload chunks of a FETCH response."""
        payload = bytearray()
        for item in self._fetch(uid, spec):
            if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
                payload += item[1]
        return bytes(payload)

    def _fetch_response_text(self, uid: int, spec: str) -> bytes:
        """Return the entire FETCH response line including literal chunks."""
        payload = bytearray()
        for item in self._fetch(uid, spec):
            if isinstance(item, tuple):
                for piece in item:
                    if isinstance(piece, bytes):
                        payload += piece
            elif isinstance(item, bytes):
                payload += item
        return bytes(payload)


# ----------------------------------------------------------------------
# Helpers


def _response_int(values, default: int = 0) -> int:
    """Best-effort int extraction from an untagged response list."""
    if not values:
        return default
    try:
        first = values[0]
        if isinstance(first, bytes):
            first = first.decode("ascii", errors="replace")
        return int(first)
    except (TypeError, ValueError):
        return default


def _safe_detail(exc: BaseException) -> str:
    """Trim exception text so no credentials leak into logs."""
    text = str(exc)
    return text[:200]


def _select_error(name: str, id_supported: bool | None, exc: BaseException | None) -> MailSyncError:
    detail = _safe_detail(exc) if exc is not None else ""
    if id_supported is False:
        return MailSyncError(
            MailErrorCode.IMAP_ID_UNSUPPORTED,
            "服务器拒绝了客户端 ID 声明或因此拒绝访问目录",
            detail=detail,
        )
    return MailSyncError(
        MailErrorCode.MAILBOX_SELECT_FAILED,
        f"无法打开邮件文件夹: {name}",
        detail=detail,
    )


_LIST_RE = re.compile(
    r'^\((?P<flags>[^)]*)\)\s+"(?P<delim>[^"]*)"\s+(?P<name>.+?)\s*$'
)


def _parse_list_line(line: bytes | str) -> MailFolder | None:
    if isinstance(line, bytes):
        line = line.decode("utf-8", errors="replace")
    match = _LIST_RE.match(line)
    if not match:
        return None
    flags = tuple(flag.upper() for flag in match.group("flags").split() if flag)
    raw_name = match.group("name").strip()
    if raw_name.startswith('"') and raw_name.endswith('"'):
        raw_name = raw_name[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    selectable = "\\NOSELECT" not in flags
    return MailFolder(
        name=decode_imap_utf7(raw_name),
        raw_name=raw_name,
        flags=flags,
        delimiter=match.group("delim"),
        selectable=selectable,
    )


def _parse_sexp(text: str, start: int) -> tuple[object, int]:
    """Parse a parenthesized IMAP s-expression starting at ``start``."""
    pos = start

    def parse_list() -> list:
        nonlocal pos
        items: list = []
        while pos < len(text):
            pos = _skip_ws(text, pos)
            if pos >= len(text):
                break
            if text[pos] == ")":
                pos += 1
                return items
            items.append(parse_item())
        return items

    def parse_item() -> object:
        nonlocal pos
        if text[pos] == "(":
            pos += 1
            return parse_list()
        if text[pos] == '"':
            end = pos + 1
            buf: list[str] = []
            while end < len(text):
                ch = text[end]
                if ch == "\\" and end + 1 < len(text):
                    buf.append(text[end + 1])
                    end += 2
                    continue
                if ch == '"':
                    end += 1
                    break
                buf.append(ch)
                end += 1
            value = "".join(buf)
            pos = end
            return value
        if text[pos] == "{":
            literal = re.match(r"\{(\d+)\}", text[pos:])
            if literal:
                # IMAP literal: {n}\r\n followed by exactly n raw bytes —
                # NetEase uses this for non-ASCII parameter values. imaplib
                # strips the CRLF when it stitches the literal into the
                # response line, leaving "{n}<content>" directly attached,
                # so consume n BYTES worth of characters either way.
                length = int(literal.group(1))
                pos += literal.end()
                if text.startswith("\r\n", pos):
                    pos += 2
                elif text.startswith("\n", pos):
                    pos += 1
                end = pos
                acc = 0
                while end < len(text) and acc < length:
                    acc += len(text[end].encode("utf-8"))
                    end += 1
                if acc != length:  # malformed length — fall back to chars
                    end = min(pos + length, len(text))
                value = text[pos:end]
                pos = end
                return value
        # atom
        end = pos
        while end < len(text) and text[end] not in "() \r\n":
            end += 1
        atom = text[pos:end]
        pos = end
        if atom.upper() == "NIL":
            return None
        return atom

    result = parse_item()
    return result, pos


def _skip_ws(text: str, pos: int) -> int:
    while pos < len(text) and text[pos] in " \r\n":
        pos += 1
    return pos
