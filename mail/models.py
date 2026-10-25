"""Data models for mail accounts, folders, attachments, and sync state."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field

NETEASE_163 = "netease_163"
NETEASE_126 = "netease_126"
NETEASE_ENTERPRISE = "netease_enterprise"
CUSTOM = "custom"

SERVER_PRESETS: dict[str, dict[str, object]] = {
    NETEASE_163: {
        "label": "网易 163",
        "host": "imap.163.com",
        "port": 993,
        "use_ssl": True,
        "domains": ["163.com"],
    },
    NETEASE_126: {
        "label": "网易 126",
        "host": "imap.126.com",
        "port": 993,
        "use_ssl": True,
        "domains": ["126.com"],
    },
    NETEASE_ENTERPRISE: {
        "label": "网易企业邮箱",
        "host": "imaphz.qiye.163.com",
        "port": 993,
        "use_ssl": True,
        "domains": [],
    },
    CUSTOM: {
        "label": "自定义 IMAP",
        "host": "",
        "port": 993,
        "use_ssl": True,
        "domains": [],
    },
}


def guess_preset_for_email(email: str) -> str:
    """Pick a server preset based on the email domain."""
    domain = email.rsplit("@", 1)[-1].lower() if "@" in email else ""
    for preset_id, preset in SERVER_PRESETS.items():
        if domain in preset["domains"]:
            return preset_id
    if domain.endswith(".163.com") or domain == "qiye.163.com":
        return NETEASE_ENTERPRISE
    return CUSTOM


@dataclass(slots=True)
class MailFilterConfig:
    """User-configurable attachment selection rules."""

    senders: list[str] = field(default_factory=list)
    subject_keywords: list[str] = field(default_factory=list)
    attachment_extensions: list[str] = field(default_factory=lambda: [".pdf"])
    attachment_name_keywords: list[str] = field(default_factory=list)
    max_attachment_mb: int = 50

    def normalized_extensions(self) -> set[str]:
        return {
            ext.casefold() if ext.startswith(".") else f".{ext.casefold()}"
            for ext in self.attachment_extensions
        }

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "MailFilterConfig":
        if not isinstance(data, dict):
            return cls()
        merged = cls()
        for key in (
            "senders",
            "subject_keywords",
            "attachment_extensions",
            "attachment_name_keywords",
            "max_attachment_mb",
        ):
            if key in data:
                setattr(merged, key, data[key])
        return merged


@dataclass(slots=True)
class MailAccountConfig:
    """Non-secret mail account settings persisted in config.json."""

    account_id: str = ""
    label: str = ""
    email: str = ""
    preset: str = NETEASE_163
    host: str = "imap.163.com"
    port: int = 993
    use_ssl: bool = True
    enabled: bool = True
    folders: list[str] = field(default_factory=list)
    filters: MailFilterConfig = field(default_factory=MailFilterConfig)
    sync_interval_minutes: int = 15
    import_to_pending: bool = True
    last_sync_at: str = ""
    last_error: str = ""
    last_error_code: str = ""

    def __post_init__(self) -> None:
        if not self.account_id:
            self.account_id = uuid.uuid4().hex[:12]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "MailAccountConfig":
        if not isinstance(data, dict):
            return cls()
        account = cls()
        for key in (
            "account_id",
            "label",
            "email",
            "preset",
            "host",
            "port",
            "use_ssl",
            "enabled",
            "folders",
            "sync_interval_minutes",
            "import_to_pending",
            "last_sync_at",
            "last_error",
            "last_error_code",
        ):
            if key in data:
                setattr(account, key, data[key])
        if "filters" in data:
            account.filters = MailFilterConfig.from_dict(data["filters"])
        return account


@dataclass(slots=True)
class MailConfig:
    """Mail synchronization settings stored inside AppConfig."""

    auto_sync_enabled: bool = True
    poll_interval_minutes: int = 15
    batch_size: int = 50
    raw_dir_name: str = "邮件原始附件"
    accounts: list[MailAccountConfig] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["accounts"] = [account.to_dict() for account in self.accounts]
        return data

    @classmethod
    def from_dict(cls, data: dict | None) -> "MailConfig":
        if not isinstance(data, dict):
            return cls()
        config = cls()
        for key in ("auto_sync_enabled", "poll_interval_minutes", "batch_size", "raw_dir_name"):
            if key in data:
                setattr(config, key, data[key])
        config.accounts = [
            MailAccountConfig.from_dict(item)
            for item in data.get("accounts", [])
            if isinstance(item, dict)
        ]
        return config


@dataclass(slots=True)
class MailFolder:
    """An IMAP folder as reported by the server."""

    name: str
    raw_name: str = ""
    flags: tuple[str, ...] = ()
    delimiter: str = "/"
    selectable: bool = True
    message_count: int = -1
    uidvalidity: int = 0


@dataclass(slots=True)
class AttachmentPart:
    """A single attachment discovered via BODYSTRUCTURE."""

    index: int
    part_number: str
    filename: str
    content_type: str
    size: int
    is_inline_with_name: bool = False


@dataclass(slots=True)
class MessageInfo:
    """Minimal headers tracked for source tracing."""

    uid: int
    message_id: str = ""
    subject: str = ""
    sender: str = ""
    date: str = ""


@dataclass(slots=True)
class SyncStatusSnapshot:
    """A GUI-friendly view of the current sync run."""

    running: bool = False
    paused: bool = False
    account_label: str = ""
    folder_name: str = ""
    mode: str = ""
    processed: int = 0
    total: int = 0
    downloaded: int = 0
    skipped_duplicate: int = 0
    failed: int = 0
    last_error: str = ""
    last_error_code: str = ""


@dataclass(slots=True)
class ConnectionProbeResult:
    """Outcome of a staged connection test."""

    ok: bool
    stage: str
    code: str = ""
    message: str = ""
    folders: list[MailFolder] = field(default_factory=list)
