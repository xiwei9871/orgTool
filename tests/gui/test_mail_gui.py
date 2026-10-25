"""GUI tests for the mail sync panel, dialogs, and main-window wiring."""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

import gui.main_window as main_window_module
from config.schema import AppConfig
from gui.dialogs.backfill_dialog import BackfillDialog
from gui.dialogs.mail_account_dialog import MailAccountDialog
from gui.main_window import MainWindow
from gui.pages.mail_panel import MailSyncPanel
from mail.credentials import InMemoryCredentialStore
from mail.models import MailAccountConfig, SyncStatusSnapshot
from services.mail_service import MailService
from utils.paths import RuntimePaths

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _app() -> QApplication:
    app = QApplication.instance()
    return app if app is not None else QApplication(sys.argv)


def _paths(tmp_path: Path) -> RuntimePaths:
    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure_dirs()
    return paths


# ----------------------------------------------------------------------
# Panel


def test_panel_accounts_and_selection() -> None:
    _app()
    panel = MailSyncPanel()
    account = MailAccountConfig()
    account.label = "我的163"
    account.email = "me@163.com"
    account.folders = ["INBOX", "发票"]
    panel.set_accounts([account])
    assert panel.accounts_table.rowCount() == 1
    panel.accounts_table.selectRow(0)
    assert panel.selected_account_id() == account.account_id


def test_panel_status_updates() -> None:
    _app()
    panel = MailSyncPanel()
    snapshot = SyncStatusSnapshot(
        running=True, processed=3, total=10, downloaded=2,
        skipped_duplicate=1, failed=0, folder_name="INBOX",
    )
    panel.update_status(snapshot, {"done": 2, "pending": 1})
    assert "3" in panel.stats_label.text()
    snapshot2 = SyncStatusSnapshot(running=False)
    panel.update_status(snapshot2, {})
    assert panel.progress_bar.format() == "空闲"


# ----------------------------------------------------------------------
# Account dialog


def test_account_dialog_roundtrip() -> None:
    _app()
    dialog = MailAccountDialog()
    dialog.label_input.setText("测试")
    dialog.email_input.setText("user@163.com")
    dialog.secret_input.setText("auth-code")
    dialog.set_folder_names(["INBOX", "发票"], selected=["INBOX"])
    account = dialog.build_account()
    assert account.email == "user@163.com"
    assert account.folders == ["INBOX"]
    assert dialog.secret() == "auth-code"


def test_account_dialog_126_preset() -> None:
    _app()
    dialog = MailAccountDialog()
    dialog.email_input.setText("user@126.com")
    dialog._apply_guessed_preset()
    assert dialog.preset_combo.currentData() == "netease_126"
    assert dialog.host_input.text() == "imap.126.com"


def test_account_dialog_enterprise_preset_not_mixed() -> None:
    _app()
    dialog = MailAccountDialog()
    dialog.email_input.setText("user@corp.163.com")
    dialog._apply_guessed_preset()
    assert dialog.preset_combo.currentData() == "netease_enterprise"
    assert dialog.host_input.text() != "imap.163.com"


def test_account_dialog_rejects_missing_fields(monkeypatch) -> None:
    _app()
    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda *a, **k: warnings.append(a))
    )
    dialog = MailAccountDialog()
    dialog.email_input.setText("")
    accepted = []
    monkeypatch.setattr(dialog, "accept", lambda: accepted.append(1))
    dialog._on_accept()
    assert not accepted
    assert warnings


def test_account_dialog_preserves_existing_secret() -> None:
    _app()
    account = MailAccountConfig()
    account.email = "u@163.com"
    dialog = MailAccountDialog(account=account, existing_secret="old-code")
    assert dialog.secret() == "old-code"
    dialog.secret_input.setText("new-code")
    assert dialog.secret() == "new-code"


# ----------------------------------------------------------------------
# Backfill dialog


def test_backfill_dialog_defaults_all_history() -> None:
    _app()
    dialog = BackfillDialog(["INBOX", "发票"])
    assert dialog.selected_folders() == ["INBOX", "发票"]
    since, until = dialog.date_range()
    assert since is None and until is None


def test_backfill_dialog_range_mode() -> None:
    _app()
    dialog = BackfillDialog(["INBOX"])
    dialog.range_radio.setChecked(True)
    since, until = dialog.date_range()
    assert isinstance(since, date) and isinstance(until, date)
    assert since <= until


def test_backfill_dialog_requires_folder(monkeypatch) -> None:
    _app()
    warnings = []
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda *a, **k: warnings.append(a))
    )
    dialog = BackfillDialog(["INBOX"])
    item = dialog.folders_list.item(0)
    item.setCheckState(item.checkState().Unchecked)
    accepted = []
    monkeypatch.setattr(dialog, "accept", lambda: accepted.append(1))
    dialog._on_accept()
    assert not accepted
    assert warnings


# ----------------------------------------------------------------------
# Main window wiring


def _install_fake_manager(monkeypatch, config: AppConfig, paths: RuntimePaths):
    fake_manager = SimpleNamespace(
        load=lambda: config,
        save=lambda updated: updated,
        paths=paths,
    )
    monkeypatch.setattr(
        main_window_module.ConfigManager,
        "for_app",
        classmethod(lambda cls: fake_manager),
    )


def _window(tmp_path: Path, monkeypatch) -> MainWindow:
    _app()
    config = AppConfig()
    config.invoice.root_dir = str(tmp_path / "发票管理")
    paths = _paths(tmp_path)
    _install_fake_manager(monkeypatch, config, paths)
    monkeypatch.setattr(
        main_window_module,
        "resolve_desktop_directory",
        lambda: tmp_path,
    )
    original = MailService.__init__

    def patched_init(self, runtime_paths, config_getter, config_saver=None,
                     credential_store=None, client_factory=None,
                     engine_factory=None):
        original(
            self, runtime_paths, config_getter, config_saver,
            credential_store=InMemoryCredentialStore(),
            client_factory=client_factory,
            engine_factory=engine_factory,
        )

    monkeypatch.setattr(MailService, "__init__", patched_init)
    return MainWindow()


def test_main_window_has_mail_panel_and_service(tmp_path, monkeypatch) -> None:
    window = _window(tmp_path, monkeypatch)
    assert window.invoice_page.mail_panel is not None
    assert window.mail_service.running is False
    window.close()


def test_mail_status_timer_ticks_and_keeps_selection(
    tmp_path, monkeypatch
) -> None:
    window = _window(tmp_path, monkeypatch)
    account = MailAccountConfig()
    account.email = "u@163.com"
    window.mail_service.upsert_account(
        account, secret="s", persist=window._persist_mail_config
    )
    window._mail_accounts_fp = None
    window._refresh_mail_accounts()
    panel = window.invoice_page.mail_panel
    panel.accounts_table.selectRow(0)
    # Two consecutive status refreshes must not rebuild the table.
    window._refresh_mail_status()
    window._refresh_mail_status()
    assert panel.selected_account_id() == account.account_id
    window.close()


def test_sync_finished_triggers_invoice_scan(tmp_path, monkeypatch) -> None:
    window = _window(tmp_path, monkeypatch)
    scans = []
    monkeypatch.setattr(window, "scan_invoices", lambda: scans.append(1))
    window._mail_was_running = True
    snap = SyncStatusSnapshot(running=False, downloaded=3)
    monkeypatch.setattr(window.mail_service, "status", lambda: snap)
    window._refresh_mail_status()
    assert scans == [1]
    window.close()
