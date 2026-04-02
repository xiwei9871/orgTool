"""Configuration loading and saving."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, TypeVar

from config.defaults import DEFAULT_APP_NAME
from config.schema import AppConfig, DesktopConfig, GeneralConfig, InvoiceConfig
from utils.paths import RuntimePaths

T = TypeVar("T")


class ConfigManager:
    """Load and persist application configuration."""

    def __init__(self, paths: RuntimePaths) -> None:
        self.paths = paths

    @classmethod
    def for_app(cls, app_name: str = DEFAULT_APP_NAME) -> "ConfigManager":
        """Create a config manager bound to the app runtime location."""
        return cls(RuntimePaths.from_env(app_name))

    def load(self) -> AppConfig:
        """Load configuration from disk or return defaults when missing."""
        if not self.paths.config_file.exists():
            return AppConfig()

        data = json.loads(self.paths.config_file.read_text(encoding="utf-8"))
        return AppConfig(
            general=_merge_dataclass(GeneralConfig(), data.get("general", {})),
            desktop=_merge_dataclass(DesktopConfig(), data.get("desktop", {})),
            invoice=_merge_dataclass(InvoiceConfig(), data.get("invoice", {})),
        )

    def save(self, config: AppConfig) -> Path:
        """Persist configuration to disk as UTF-8 JSON."""
        self.paths.root.mkdir(parents=True, exist_ok=True)
        self.paths.config_file.write_text(
            json.dumps(config.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return self.paths.config_file


def _merge_dataclass(instance: T, values: dict[str, Any]) -> T:
    """Overlay loaded values onto a dataclass instance."""
    if not is_dataclass(instance):
        return instance

    kwargs: dict[str, Any] = {}
    for field_info in fields(instance):
        current_value = getattr(instance, field_info.name)
        incoming_value = values.get(field_info.name, current_value)

        if is_dataclass(current_value) and isinstance(incoming_value, dict):
            kwargs[field_info.name] = _merge_dataclass(current_value, incoming_value)
        else:
            kwargs[field_info.name] = incoming_value

    return type(instance)(**kwargs)
