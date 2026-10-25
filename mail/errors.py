"""Structured error codes for mail synchronization."""

from __future__ import annotations


class MailErrorCode:
    """Stable error codes surfaced in UI, logs, and reports."""

    AUTH_FAILED = "AUTH_FAILED"
    AUTH_CODE_REQUIRED = "AUTH_CODE_REQUIRED"
    IMAP_ID_UNSUPPORTED = "IMAP_ID_UNSUPPORTED"
    MAILBOX_SELECT_FAILED = "MAILBOX_SELECT_FAILED"
    FOLDER_NOT_FOUND = "FOLDER_NOT_FOUND"
    SERVER_HISTORY_LIMIT = "SERVER_HISTORY_LIMIT"
    NETWORK_TIMEOUT = "NETWORK_TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    ATTACHMENT_DECODE_FAILED = "ATTACHMENT_DECODE_FAILED"
    FILE_WRITE_FAILED = "FILE_WRITE_FAILED"
    DOWNLOAD_INTERRUPTED = "DOWNLOAD_INTERRUPTED"
    INVALID_PDF = "INVALID_PDF"
    SYNC_CONFLICT = "SYNC_CONFLICT"
    CREDENTIAL_STORE_UNAVAILABLE = "CREDENTIAL_STORE_UNAVAILABLE"


class MailSyncError(Exception):
    """A mail synchronization failure carrying a stable error code."""

    def __init__(self, code: str, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail

    def __str__(self) -> str:
        if self.detail:
            return f"[{self.code}] {self.message} ({self.detail})"
        return f"[{self.code}] {self.message}"
