"""Application entry point."""

from __future__ import annotations

from app import create_application, create_main_window


def main() -> int:
    """Run the desktop organizer application."""
    app = create_application()
    window = create_main_window()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
