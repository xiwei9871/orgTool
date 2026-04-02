"""Application bootstrap helpers."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from gui.main_window import MainWindow


def create_application(argv: list[str] | None = None) -> QApplication:
    """Create and return the Qt application instance."""
    app = QApplication.instance()
    return app if app is not None else QApplication(argv or sys.argv)


def create_main_window() -> MainWindow:
    """Create the top-level main window."""
    return MainWindow()
