"""Mail test helpers; fixtures live in tests/conftest.py for reuse."""

from __future__ import annotations

# Re-export so `from tests.mail.conftest import ...` keeps working.
from tests.conftest import (  # noqa: F401
    VALID_PDF,
    seed_account,
    seed_folder,
)
