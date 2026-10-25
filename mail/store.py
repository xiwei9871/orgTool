"""SQLite-backed state store for mail synchronization.

Tracks folders, per-message-attachment download records, and per-folder
sync task progress so backfills and incremental syncs can resume after
network failures, cancellation, or application shutdown.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 1

STATUS_PENDING = "pending"
STATUS_DOWNLOADING = "downloading"
STATUS_DONE = "done"
STATUS_SKIPPED_DUPLICATE = "skipped_duplicate"
STATUS_FAILED = "failed"
STATUS_SERVER_UNAVAILABLE = "server_unavailable"

TASK_RUNNING = "running"
TASK_PAUSED = "paused"
TASK_DONE = "done"
TASK_FAILED = "failed"
TASK_CANCELLED = "cancelled"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS folders (
    id INTEGER PRIMARY KEY,
    account_id TEXT NOT NULL,
    name TEXT NOT NULL,
    uidvalidity INTEGER DEFAULT 0,
    last_seen_uid INTEGER DEFAULT 0,
    updated_at TEXT,
    UNIQUE(account_id, name)
);
CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY,
    account_id TEXT NOT NULL,
    folder_id INTEGER NOT NULL,
    uidvalidity INTEGER NOT NULL,
    uid INTEGER NOT NULL,
    message_id TEXT,
    subject TEXT,
    sender TEXT,
    message_date TEXT,
    attachment_index INTEGER NOT NULL,
    attachment_name TEXT,
    part_number TEXT,
    size INTEGER DEFAULT 0,
    content_hash TEXT,
    download_status TEXT NOT NULL DEFAULT 'pending',
    local_path TEXT,
    last_error TEXT,
    last_error_code TEXT,
    attempts INTEGER DEFAULT 0,
    updated_at TEXT NOT NULL,
    UNIQUE(account_id, folder_id, uidvalidity, uid, attachment_index)
);
CREATE INDEX IF NOT EXISTS idx_attachments_hash ON attachments(content_hash);
CREATE INDEX IF NOT EXISTS idx_attachments_status
    ON attachments(account_id, download_status);
CREATE TABLE IF NOT EXISTS sync_tasks (
    id INTEGER PRIMARY KEY,
    account_id TEXT NOT NULL,
    folder_id INTEGER,
    folder_name TEXT,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    since_date TEXT,
    until_date TEXT,
    cursor_uid INTEGER DEFAULT 0,
    processed INTEGER DEFAULT 0,
    total INTEGER DEFAULT 0,
    found INTEGER DEFAULT 0,
    downloaded INTEGER DEFAULT 0,
    skipped_duplicate INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


@dataclass(slots=True)
class AttachmentRecord:
    id: int
    account_id: str
    folder_id: int
    uidvalidity: int
    uid: int
    message_id: str
    subject: str
    sender: str
    message_date: str
    attachment_index: int
    attachment_name: str
    part_number: str
    size: int
    content_hash: str | None
    download_status: str
    local_path: str
    last_error: str
    last_error_code: str
    attempts: int
    updated_at: str


@dataclass(slots=True)
class FolderRecord:
    id: int
    account_id: str
    name: str
    uidvalidity: int
    last_seen_uid: int
    updated_at: str


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class MailSyncStore:
    """Thread-safe SQLite wrapper for sync state."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            self.db_path, check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._migrate()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def _tx(self):
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                yield self._conn
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    def _migrate(self) -> None:
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, _now()),
            )

    def backup_to(self, target: Path) -> Path:
        """Create a consistent backup copy of the database."""
        with self._lock:
            target.parent.mkdir(parents=True, exist_ok=True)
            backup = sqlite3.connect(target)
            try:
                self._conn.backup(backup)
            finally:
                backup.close()
        return target

    def check_integrity(self) -> bool:
        """Return True when the database passes a quick integrity check."""
        with self._lock:
            row = self._conn.execute("PRAGMA quick_check").fetchone()
            return row is not None and row[0] == "ok"

    # ------------------------------------------------------------------
    # Folders

    def upsert_folder(self, account_id: str, name: str) -> FolderRecord:
        with self._tx() as conn:
            conn.execute(
                """INSERT INTO folders(account_id, name, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(account_id, name) DO NOTHING""",
                (account_id, name, _now()),
            )
        row = self._conn.execute(
            "SELECT * FROM folders WHERE account_id=? AND name=?",
            (account_id, name),
        ).fetchone()
        return _folder_from_row(row)

    def get_folder(self, account_id: str, name: str) -> FolderRecord | None:
        row = self._conn.execute(
            "SELECT * FROM folders WHERE account_id=? AND name=?",
            (account_id, name),
        ).fetchone()
        return _folder_from_row(row) if row else None

    def get_folder_by_id(self, folder_id: int) -> FolderRecord | None:
        row = self._conn.execute(
            "SELECT * FROM folders WHERE id=?", (folder_id,)
        ).fetchone()
        return _folder_from_row(row) if row else None

    def update_folder_state(
        self,
        folder_id: int,
        uidvalidity: int | None = None,
        last_seen_uid: int | None = None,
    ) -> None:
        with self._tx() as conn:
            if uidvalidity is not None:
                conn.execute(
                    "UPDATE folders SET uidvalidity=?, updated_at=? WHERE id=?",
                    (uidvalidity, _now(), folder_id),
                )
            if last_seen_uid is not None:
                conn.execute(
                    "UPDATE folders SET last_seen_uid=?, updated_at=? WHERE id=?",
                    (last_seen_uid, _now(), folder_id),
                )

    # ------------------------------------------------------------------
    # Attachment records

    def upsert_attachment(
        self,
        account_id: str,
        folder_id: int,
        uidvalidity: int,
        uid: int,
        message_id: str,
        subject: str,
        sender: str,
        message_date: str,
        attachment_index: int,
        attachment_name: str,
        part_number: str,
        size: int,
    ) -> AttachmentRecord:
        """Insert a candidate record if absent; return the existing/new row."""
        with self._tx() as conn:
            conn.execute(
                """INSERT INTO attachments(
                       account_id, folder_id, uidvalidity, uid, message_id,
                       subject, sender, message_date, attachment_index,
                       attachment_name, part_number, size, download_status,
                       local_path, updated_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, '', ?)
                   ON CONFLICT(account_id, folder_id, uidvalidity, uid, attachment_index)
                   DO NOTHING""",
                (
                    account_id,
                    folder_id,
                    uidvalidity,
                    uid,
                    message_id,
                    subject,
                    sender,
                    message_date,
                    attachment_index,
                    attachment_name,
                    part_number,
                    size,
                    STATUS_PENDING,
                    _now(),
                ),
            )
        row = self._conn.execute(
            """SELECT * FROM attachments
               WHERE account_id=? AND folder_id=? AND uidvalidity=? AND uid=?
                 AND attachment_index=?""",
            (account_id, folder_id, uidvalidity, uid, attachment_index),
        ).fetchone()
        return _attachment_from_row(row)

    def get_attachment(self, record_id: int) -> AttachmentRecord | None:
        row = self._conn.execute(
            "SELECT * FROM attachments WHERE id=?", (record_id,)
        ).fetchone()
        return _attachment_from_row(row) if row else None

    def mark_attachment(
        self,
        record_id: int,
        status: str,
        local_path: str = "",
        content_hash: str | None = None,
        last_error: str = "",
        last_error_code: str = "",
        increment_attempts: bool = False,
    ) -> None:
        with self._tx() as conn:
            conn.execute(
                """UPDATE attachments SET
                       download_status=?,
                       local_path=CASE WHEN ? != '' THEN ? ELSE local_path END,
                       content_hash=COALESCE(?, content_hash),
                       last_error=?,
                       last_error_code=?,
                       attempts=attempts + ?,
                       updated_at=?
                   WHERE id=?""",
                (
                    status,
                    local_path,
                    local_path,
                    content_hash,
                    last_error,
                    last_error_code,
                    1 if increment_attempts else 0,
                    _now(),
                    record_id,
                ),
            )

    def update_attachment_meta(
        self,
        record_id: int,
        attachment_name: str | None = None,
        part_number: str | None = None,
    ) -> None:
        """Refresh mutable metadata (name/part) after a bodystructure refresh."""
        fields: list[str] = []
        values: list = []
        if attachment_name:
            fields.append("attachment_name=?")
            values.append(attachment_name)
        if part_number:
            fields.append("part_number=?")
            values.append(part_number)
        if not fields:
            return
        fields.append("updated_at=?")
        values += [_now(), record_id]
        with self._tx() as conn:
            conn.execute(
                f"UPDATE attachments SET {', '.join(fields)} WHERE id=?",
                tuple(values),
            )

    def done_records(self, account_id: str) -> list[AttachmentRecord]:
        rows = self._conn.execute(
            """SELECT * FROM attachments
               WHERE account_id=? AND download_status='done'""",
            (account_id,),
        ).fetchall()
        return [_attachment_from_row(row) for row in rows]

    def find_by_hash(
        self, content_hash: str, exclude_id: int | None = None
    ) -> AttachmentRecord | None:
        """Locate a previously downloaded attachment with identical content."""
        if not content_hash:
            return None
        if exclude_id is None:
            row = self._conn.execute(
                """SELECT * FROM attachments
                   WHERE content_hash=? AND download_status IN ('done','skipped_duplicate')
                   ORDER BY id LIMIT 1""",
                (content_hash,),
            ).fetchone()
        else:
            row = self._conn.execute(
                """SELECT * FROM attachments
                   WHERE content_hash=? AND id != ?
                     AND download_status IN ('done','skipped_duplicate')
                   ORDER BY id LIMIT 1""",
                (content_hash, exclude_id),
            ).fetchone()
        return _attachment_from_row(row) if row else None

    def pending_for_folder(
        self, account_id: str, folder_id: int, uidvalidity: int
    ) -> list[AttachmentRecord]:
        rows = self._conn.execute(
            """SELECT * FROM attachments
               WHERE account_id=? AND folder_id=? AND uidvalidity=?
                 AND download_status IN ('pending','downloading')
               ORDER BY uid, attachment_index""",
            (account_id, folder_id, uidvalidity),
        ).fetchall()
        return [_attachment_from_row(row) for row in rows]

    def retryable_failures(
        self, account_id: str, max_attempts: int
    ) -> list[AttachmentRecord]:
        rows = self._conn.execute(
            """SELECT * FROM attachments
               WHERE account_id=? AND download_status IN ('failed','server_unavailable')
                 AND attempts < ?
               ORDER BY uid""",
            (account_id, max_attempts),
        ).fetchall()
        return [_attachment_from_row(row) for row in rows]

    def reset_downloading(self, account_id: str) -> int:
        """Recover records left mid-download by an abrupt shutdown."""
        with self._tx() as conn:
            cursor = conn.execute(
                """UPDATE attachments SET download_status=?, updated_at=?
                   WHERE account_id=? AND download_status=?""",
                (STATUS_PENDING, _now(), account_id, STATUS_DOWNLOADING),
            )
            return cursor.rowcount

    def count_by_status(self, account_id: str) -> dict[str, int]:
        rows = self._conn.execute(
            """SELECT download_status, COUNT(*) AS n FROM attachments
               WHERE account_id=? GROUP BY download_status""",
            (account_id,),
        ).fetchall()
        return {row["download_status"]: row["n"] for row in rows}

    # ------------------------------------------------------------------
    # Sync tasks

    def create_task(
        self,
        account_id: str,
        folder_id: int | None,
        folder_name: str,
        mode: str,
        since_date: str = "",
        until_date: str = "",
    ) -> int:
        with self._tx() as conn:
            cursor = conn.execute(
                """INSERT INTO sync_tasks(
                       account_id, folder_id, folder_name, mode, status,
                       since_date, until_date, created_at, updated_at
                   ) VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    account_id,
                    folder_id,
                    folder_name,
                    mode,
                    TASK_RUNNING,
                    since_date,
                    until_date,
                    _now(),
                    _now(),
                ),
            )
            return int(cursor.lastrowid)

    def update_task(self, task_id: int, **fields) -> None:
        allowed = {
            "status",
            "cursor_uid",
            "processed",
            "total",
            "found",
            "downloaded",
            "skipped_duplicate",
            "failed",
            "last_error",
        }
        assignments = [f"{key}=?" for key in fields if key in allowed]
        if not assignments:
            return
        values = [fields[key] for key in fields if key in allowed]
        assignments.append("updated_at=?")
        values.append(_now())
        values.append(task_id)
        with self._tx() as conn:
            conn.execute(
                f"UPDATE sync_tasks SET {', '.join(assignments)} WHERE id=?",
                tuple(values),
            )

    def get_task(self, task_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM sync_tasks WHERE id=?", (task_id,)
        ).fetchone()
        return dict(row) if row else None

    def latest_task_for_folder(
        self, account_id: str, folder_id: int, mode: str
    ) -> dict | None:
        row = self._conn.execute(
            """SELECT * FROM sync_tasks
               WHERE account_id=? AND folder_id=? AND mode=?
               ORDER BY id DESC LIMIT 1""",
            (account_id, folder_id, mode),
        ).fetchone()
        return dict(row) if row else None

    def latest_tasks(self, limit: int = 10) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM sync_tasks ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

    def unfinished_tasks(self, account_id: str) -> list[dict]:
        rows = self._conn.execute(
            """SELECT * FROM sync_tasks
               WHERE account_id=? AND status IN ('running','paused')
               ORDER BY id""",
            (account_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def dump_diagnostics(self) -> str:
        """Serialize high-level sync state for support diagnostics."""
        with self._lock:
            folders = self._conn.execute("SELECT * FROM folders").fetchall()
            tasks = self._conn.execute(
                "SELECT * FROM sync_tasks ORDER BY id DESC LIMIT 20"
            ).fetchall()
            counts = self._conn.execute(
                """SELECT account_id, download_status, COUNT(*) AS n
                   FROM attachments GROUP BY account_id, download_status"""
            ).fetchall()
        return json.dumps(
            {
                "folders": [dict(row) for row in folders],
                "recent_tasks": [dict(row) for row in tasks],
                "attachment_counts": [dict(row) for row in counts],
            },
            ensure_ascii=False,
            indent=2,
        )


def _folder_from_row(row: sqlite3.Row) -> FolderRecord:
    return FolderRecord(
        id=row["id"],
        account_id=row["account_id"],
        name=row["name"],
        uidvalidity=row["uidvalidity"] or 0,
        last_seen_uid=row["last_seen_uid"] or 0,
        updated_at=row["updated_at"] or "",
    )


def _attachment_from_row(row: sqlite3.Row) -> AttachmentRecord:
    return AttachmentRecord(
        id=row["id"],
        account_id=row["account_id"],
        folder_id=row["folder_id"],
        uidvalidity=row["uidvalidity"],
        uid=row["uid"],
        message_id=row["message_id"] or "",
        subject=row["subject"] or "",
        sender=row["sender"] or "",
        message_date=row["message_date"] or "",
        attachment_index=row["attachment_index"],
        attachment_name=row["attachment_name"] or "",
        part_number=row["part_number"] or "",
        size=row["size"] or 0,
        content_hash=row["content_hash"],
        download_status=row["download_status"],
        local_path=row["local_path"] or "",
        last_error=row["last_error"] or "",
        last_error_code=row["last_error_code"] or "",
        attempts=row["attempts"] or 0,
        updated_at=row["updated_at"] or "",
    )
