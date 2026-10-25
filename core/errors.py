"""Shared exceptions for cancellable operations."""

from __future__ import annotations

import threading


class OperationCancelled(Exception):
    """Raised when a running operation observes its cancellation event."""


def raise_if_cancelled(cancel_event: threading.Event | None) -> None:
    """Raise ``OperationCancelled`` when the event has been set."""
    if cancel_event is not None and cancel_event.is_set():
        raise OperationCancelled()
