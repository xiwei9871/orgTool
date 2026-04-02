"""Smoke tests for the project bootstrap."""

from importlib import import_module


def test_app_module_exposes_factory() -> None:
    """The app bootstrap module should expose an application factory."""
    module = import_module("app")
    assert hasattr(module, "create_application")
