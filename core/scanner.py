"""Top-level desktop scanning."""

from __future__ import annotations

from pathlib import Path

from core.filters import should_skip_path
from models.desktop import DesktopItem


class DesktopScanner:
    """Enumerate top-level desktop entries without recursion."""

    def scan(
        self,
        desktop_path: Path,
        whitelist_names: set[str],
        whitelist_extensions: set[str],
        skip_hidden: bool,
        skip_system: bool,
    ) -> list[DesktopItem]:
        """Scan desktop entries and return structured items."""
        items: list[DesktopItem] = []

        for entry in sorted(desktop_path.iterdir(), key=lambda path: path.name.casefold()):
            should_skip, reason = should_skip_path(
                entry,
                whitelist_names=whitelist_names,
                whitelist_extensions=whitelist_extensions,
                skip_hidden=skip_hidden,
                skip_system=skip_system,
            )
            items.append(
                DesktopItem(
                    name=entry.name,
                    path=str(entry),
                    extension=entry.suffix.casefold(),
                    item_type=_detect_item_type(entry),
                    is_skipped=should_skip,
                    skip_reason=reason,
                )
            )

        return items


def _detect_item_type(path: Path) -> str:
    """Determine the top-level desktop item type."""
    if path.is_dir():
        return "folder"
    if path.suffix.casefold() == ".lnk":
        return "shortcut"
    return "file"
