"""Skip filters for desktop entries."""

from __future__ import annotations

from pathlib import Path

from utils.file_attrs import is_hidden, is_system


def should_skip_path(
    path: Path,
    whitelist_names: set[str],
    whitelist_extensions: set[str],
    skip_hidden: bool,
    skip_system: bool,
) -> tuple[bool, str]:
    """Return whether a path should be skipped and the reason."""
    normalized_name = path.name.casefold()
    normalized_extension = path.suffix.casefold()
    normalized_whitelist_names = {name.casefold() for name in whitelist_names}
    normalized_whitelist_extensions = {
        extension.casefold() for extension in whitelist_extensions
    }

    if normalized_name == "desktop.ini":
        return True, "desktop_ini"
    if normalized_name in normalized_whitelist_names:
        return True, "whitelist_name"
    if normalized_extension and normalized_extension in normalized_whitelist_extensions:
        return True, "whitelist_extension"
    if skip_hidden and is_hidden(path):
        return True, "hidden"
    if skip_system and is_system(path):
        return True, "system"
    return False, ""
