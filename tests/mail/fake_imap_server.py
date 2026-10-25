"""A controllable fake IMAP4rev1 server over real TCP sockets.

Exercises the real imaplib code path end-to-end: LOGIN, ID, LIST, SELECT,
UID SEARCH and UID FETCH with BODYSTRUCTURE and per-part literals. Several
failure modes are switchable to simulate NetEase quirks (ID requirement,
history capping, aborted fetches, select refusals).
"""

from __future__ import annotations

import base64
import socket
import threading
from dataclasses import dataclass, field

from mail.utf7 import decode_imap_utf7, encode_imap_utf7


@dataclass
class FakeAttachment:
    filename: str
    content_type: str
    data: bytes
    inline: bool = False
    declared_size: int | None = None  # lie about size if desired


@dataclass
class FakeMessage:
    uid: int
    subject: str = ""
    sender: str = "sender@example.com"
    date: str = "Mon, 05 Jan 2026 10:00:00 +0800"
    message_id: str = ""
    body_text: str = "hello"
    attachments: list[FakeAttachment] = field(default_factory=list)

    def header_block(self) -> bytes:
        lines = [
            f"Message-ID: {self.message_id or f'<m{self.uid}@fake>'}",
            f"Subject: {self.subject}",
            f"From: {self.sender}",
            f"Date: {self.date}",
            "MIME-Version: 1.0",
        ]
        return ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8")

    def mime_entity(self) -> bytes:
        """Assemble a minimal RFC822 message for BODY[] fetches."""
        if not self.attachments:
            return self.header_block() + self.body_text.encode("utf-8")
        boundary = "BOUNDARY-TEST"
        lines = self.header_block().decode("utf-8")
        lines += f"Content-Type: multipart/mixed; boundary={boundary}\r\n\r\n"
        lines += f"--{boundary}\r\nContent-Type: text/plain\r\n\r\n{self.body_text}\r\n"
        for attachment in self.attachments:
            disp = "inline" if attachment.inline else "attachment"
            lines += (
                f"--{boundary}\r\n"
                f"Content-Type: {attachment.content_type}; "
                f'name="{attachment.filename}"\r\n'
                f"Content-Disposition: {disp}; "
                f'filename="{attachment.filename}"\r\n'
                "Content-Transfer-Encoding: base64\r\n\r\n"
                + base64.b64encode(attachment.data).decode("ascii")
                + "\r\n"
            )
        lines += f"--{boundary}--\r\n"
        return lines.encode("utf-8")

    def bodystructure(self) -> str:
        parts = [
            '("TEXT" "PLAIN" ("CHARSET" "UTF-8") NIL NIL "7BIT" '
            f"{len(self.body_text)} {self.body_text.count(chr(10)) + 1} "
            'NIL NIL NIL NIL)'
        ]
        for attachment in self.attachments:
            declared = (
                attachment.declared_size
                if attachment.declared_size is not None
                else len(base64.b64encode(attachment.data))
            )
            disp = "INLINE" if attachment.inline else "ATTACHMENT"
            maintype, _, subtype = attachment.content_type.partition("/")
            parts.append(
                f'("{maintype.upper()}" "{subtype.upper()}" '
                f'("NAME" "{attachment.filename}") NIL NIL "BASE64" {declared} NIL '
                f'("{disp}" ("FILENAME" "{attachment.filename}")) NIL NIL)'
            )
        if not self.attachments:
            return parts[0]
        return "(" + "".join(parts) + ' "MIXED" NIL NIL NIL)'


@dataclass
class FakeFolder:
    name: str
    uidvalidity: int = 1001
    messages: list[FakeMessage] = field(default_factory=list)

    def by_uid(self, uid: int) -> FakeMessage | None:
        for message in self.messages:
            if message.uid == uid:
                return message
        return None

    @property
    def max_uid(self) -> int:
        return max((m.uid for m in self.messages), default=0)


class FakeImapServer:
    """Minimal scriptable IMAP server listening on 127.0.0.1."""

    def __init__(self) -> None:
        self.users: dict[str, str] = {}
        self.folders: dict[str, FakeFolder] = {}
        self.require_id = False
        self.fail_id = False
        self.fail_login = False
        self.fail_select: set[str] = set()
        self.history_limit: int | None = None
        self.abort_fetch_uids: set[int] = set()
        self.abort_once_uids: set[int] = set()
        self.reject_fetch_uids: set[int] = set()
        self.abort_fetch_count = 0
        self.id_sent = False
        self.id_payload = ""
        self.command_log: list[str] = []
        self._server_sock: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._conn_threads: list[threading.Thread] = []

    # ------------------------------------------------------------------
    # Lifecycle

    def start(self) -> int:
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind(("127.0.0.1", 0))
        self._server_sock.listen(8)
        self.port = self._server_sock.getsockname()[1]
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()
        return self.port

    def stop(self) -> None:
        self._stop.set()
        if self._server_sock is not None:
            try:
                self._server_sock.close()
            except OSError:
                pass
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=2)
        for thread in self._conn_threads:
            thread.join(timeout=2)

    @property
    def host(self) -> str:
        return "127.0.0.1"

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _addr = self._server_sock.accept()
            except OSError:
                return
            thread = threading.Thread(
                target=self._serve_connection, args=(conn,), daemon=True
            )
            self._conn_threads.append(thread)
            thread.start()

    # ------------------------------------------------------------------
    # Protocol

    def _serve_connection(self, conn: socket.socket) -> None:
        state = {"id_sent": False, "authenticated": False, "folder": None}
        try:
            conn.settimeout(15)
            conn.sendall(b"* OK fake IMAP4rev1 server ready\r\n")
            buffer = b""
            while True:
                try:
                    chunk = conn.recv(65536)
                except (socket.timeout, ConnectionError, OSError):
                    return
                if not chunk:
                    return
                buffer += chunk
                while b"\r\n" in buffer:
                    line, buffer = buffer.split(b"\r\n", 1)
                    self._handle_line(
                        line.decode("utf-8", errors="replace"), conn, state
                    )
        except (ConnectionError, OSError):
            return
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _handle_line(
        self, line: str, conn: socket.socket, state: dict
    ) -> None:
        self.command_log.append(line)
        parts = line.split(" ", 2)
        if len(parts) < 2:
            conn.sendall(b"* BAD empty\r\n")
            return None
        tag = parts[0]
        command = parts[1].upper()
        args = parts[2] if len(parts) > 2 else ""

        if command == "CAPABILITY":
            conn.sendall(b"* CAPABILITY IMAP4rev1 UIDPLUS ID AUTH=PLAIN\r\n")
            conn.sendall(f"{tag} OK CAPABILITY done\r\n".encode())
        elif command == "NOOP":
            conn.sendall(f"{tag} OK NOOP\r\n".encode())
        elif command == "LOGOUT":
            conn.sendall(b"* BYE bye\r\n")
            conn.sendall(f"{tag} OK LOGOUT\r\n".encode())
            return
        elif command == "LOGIN":
            user, secret = _split_args(args)
            if self.fail_login or self.users.get(user) != secret:
                conn.sendall(
                    f"{tag} NO [AUTHENTICATIONFAILED] bad credentials\r\n".encode()
                )
            else:
                state["authenticated"] = True
                conn.sendall(f"{tag} OK LOGIN done\r\n".encode())
        elif command == "ID":
            if self.fail_id:
                conn.sendall(f"{tag} BAD ID not supported\r\n".encode())
            else:
                self.id_sent = True
                self.id_payload = args
                state["id_sent"] = True
                conn.sendall(b'* ID ("name" "fake-imap" "version" "0")\r\n')
                conn.sendall(f"{tag} OK ID done\r\n".encode())
        elif command == "LIST":
            for folder in self.folders.values():
                encoded = encode_imap_utf7(folder.name)
                conn.sendall(
                    f'* LIST (\\HasNoChildren) "/" "{encoded}"\r\n'.encode("utf-8")
                )
            conn.sendall(f"{tag} OK LIST done\r\n".encode())
        elif command in {"SELECT", "EXAMINE"}:
            name = decode_imap_utf7(args.strip().strip('"'))
            if self.require_id and not state["id_sent"]:
                conn.sendall(
                    f"{tag} NO Unsafe Login. IMAP ID required\r\n".encode()
                )
            elif name in self.fail_select or name not in self.folders:
                conn.sendall(f"{tag} NO SELECT failed\r\n".encode())
            else:
                folder = self.folders[name]
                state["folder"] = folder
                conn.sendall(
                    f"* {len(folder.messages)} EXISTS\r\n"
                    f"* OK [UIDVALIDITY {folder.uidvalidity}] valid\r\n"
                    f"{tag} OK [READ-ONLY] SELECT done\r\n".encode()
                )
        elif command == "CLOSE":
            state["folder"] = None
            conn.sendall(f"{tag} OK CLOSE\r\n".encode())
        elif command == "UID" and args.upper().startswith("SEARCH"):
            self._handle_search(tag, args[6:].strip(), conn, state)
        elif command == "UID" and args.upper().startswith("FETCH"):
            self._handle_fetch(tag, args[5:].strip(), conn, state)
        else:
            conn.sendall(f"{tag} BAD unknown command\r\n".encode())

    def _handle_search(
        self, tag: str, criteria: str, conn: socket.socket, state: dict
    ) -> None:
        folder = state["folder"]
        if folder is None:
            conn.sendall(f"{tag} NO no folder selected\r\n".encode())
            return
        uids = [m.uid for m in folder.messages]
        tokens = criteria.upper().split()
        if "UID" in tokens:
            index = tokens.index("UID")
            low = tokens[index + 1].split(":")[0]
            if low.isdigit():
                uids = [u for u in uids if u >= int(low)]
        if self.history_limit is not None and "ALL" in tokens:
            uids = uids[-self.history_limit :]
        conn.sendall(f"* SEARCH {' '.join(map(str, uids))}\r\n".encode())
        conn.sendall(f"{tag} OK SEARCH done\r\n".encode())

    def _handle_fetch(
        self, tag: str, rest: str, conn: socket.socket, state: dict
    ) -> None:
        parts = rest.split(" ", 1)
        if not parts[0].isdigit():
            conn.sendall(f"{tag} BAD fetch\r\n".encode())
            return
        uid = int(parts[0])
        spec = parts[1] if len(parts) > 1 else ""
        folder = state["folder"]
        message = folder.by_uid(uid) if folder else None
        if uid in self.abort_fetch_uids or uid in self.abort_once_uids:
            self.abort_once_uids.discard(uid)
            self.abort_fetch_count += 1
            conn.close()
            return
        if message is None:
            conn.sendall(f"{tag} NO message gone\r\n".encode())
            return
        upper = spec.upper()
        if "BODYSTRUCTURE" in upper:
            payload = message.bodystructure().encode("utf-8")
            conn.sendall(
                b"* 1 FETCH (UID "
                + str(uid).encode()
                + b" BODYSTRUCTURE "
                + payload
                + b")\r\n"
            )
            conn.sendall(f"{tag} OK FETCH\r\n".encode())
            return
        if "HEADER.FIELDS" in upper:
            self._send_literal(tag, conn, uid, "BODY[HEADER.FIELDS (MESSAGE-ID SUBJECT FROM DATE)]", message.header_block())
            return
        if "BODY.PEEK[]" in upper or "BODY[]" in upper:
            self._send_literal(tag, conn, uid, "BODY[]", message.mime_entity())
            return
        match = __import__("re").search(r"BODY\.PEEK?\[(\d+(?:\.\d+)*)\]", upper)
        if match:
            part_number = match.group(1)
            try:
                index = int(part_number.split(".")[-1])
            except ValueError:
                index = 0
            attachments = message.attachments
            if uid in self.reject_fetch_uids:
                conn.sendall(f"{tag} NO fetch rejected\r\n".encode())
                return
            if index <= 1:
                # Part 1 is always the text body in fake messages.
                self._send_literal(
                    tag, conn, uid, f"BODY[{part_number}]",
                    message.body_text.encode("utf-8"),
                )
            elif index - 2 < len(attachments):
                self._send_literal(
                    tag, conn, uid, f"BODY[{part_number}]",
                    attachments[index - 2].data,
                )
            else:
                conn.sendall(f"{tag} NO no such part\r\n".encode())
            return
        conn.sendall(f"{tag} BAD unsupported fetch {spec}\r\n".encode())

    def _send_literal(
        self, tag: str, conn: socket.socket, uid: int, what: str, data: bytes
    ) -> None:
        head = f"* 1 FETCH (UID {uid} {what} {{{len(data)}}}\r\n".encode()
        conn.sendall(head + data + b")\r\n")
        conn.sendall(f"{tag} OK FETCH\r\n".encode())

    def mark_uids_gone(self, folder_name: str, uids: set[int]) -> None:
        """Simulate server-side message removal."""
        folder = self.folders[folder_name]
        folder.messages = [m for m in folder.messages if m.uid not in uids]


def _split_args(args: str) -> tuple[str, str]:
    pieces = args.split(" ", 1)
    user = pieces[0].strip('"') if pieces else ""
    secret = pieces[1].strip('"') if len(pieces) > 1 else ""
    return user, secret
