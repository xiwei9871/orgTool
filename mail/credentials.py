"""Authorization-code storage backed by the OS credential manager."""

from __future__ import annotations

import logging

from mail.errors import MailErrorCode, MailSyncError

logger = logging.getLogger(__name__)

SERVICE_NAME = "orgTool.mail"


class CredentialStore:
    """Interface for secret storage backends."""

    def get_secret(self, account_id: str) -> str | None:  # pragma: no cover
        raise NotImplementedError

    def set_secret(self, account_id: str, secret: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def delete_secret(self, account_id: str) -> None:  # pragma: no cover
        raise NotImplementedError

    def available(self) -> bool:  # pragma: no cover
        raise NotImplementedError


class KeyringCredentialStore(CredentialStore):
    """Store authorization codes in macOS Keychain / Windows Credential Manager."""

    def __init__(self, service_name: str = SERVICE_NAME) -> None:
        self.service_name = service_name

    def _keyring(self):
        try:
            import keyring
        except ImportError as exc:
            raise MailSyncError(
                MailErrorCode.CREDENTIAL_STORE_UNAVAILABLE,
                "系统凭证管理不可用：未安装 keyring",
            ) from exc
        return keyring

    def available(self) -> bool:
        try:
            self._keyring().get_keyring()
            return True
        except MailSyncError:
            return False
        except Exception:
            return False

    def get_secret(self, account_id: str) -> str | None:
        keyring = self._keyring()
        try:
            return keyring.get_password(self.service_name, account_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("keyring get_password failed: %s", type(exc).__name__)
            raise MailSyncError(
                MailErrorCode.CREDENTIAL_STORE_UNAVAILABLE,
                "读取系统凭证失败",
                detail=type(exc).__name__,
            ) from exc

    def set_secret(self, account_id: str, secret: str) -> None:
        keyring = self._keyring()
        try:
            keyring.set_password(self.service_name, account_id, secret)
        except Exception as exc:  # noqa: BLE001
            logger.warning("keyring set_password failed: %s", type(exc).__name__)
            raise MailSyncError(
                MailErrorCode.CREDENTIAL_STORE_UNAVAILABLE,
                "写入系统凭证失败",
                detail=type(exc).__name__,
            ) from exc

    def delete_secret(self, account_id: str) -> None:
        keyring = self._keyring()
        try:
            keyring.delete_password(self.service_name, account_id)
        except Exception:
            logger.info("keyring entry for %s absent or undeletable", account_id)


class InMemoryCredentialStore(CredentialStore):
    """Deterministic credential store for tests and headless environments."""

    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}

    def available(self) -> bool:
        return True

    def get_secret(self, account_id: str) -> str | None:
        return self._secrets.get(account_id)

    def set_secret(self, account_id: str, secret: str) -> None:
        self._secrets[account_id] = secret

    def delete_secret(self, account_id: str) -> None:
        self._secrets.pop(account_id, None)
