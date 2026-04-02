"""Service orchestration for desktop organization workflows."""

from __future__ import annotations

from pathlib import Path

from classifiers.desktop_classifier import DesktopClassifier
from config.schema import AppConfig
from core.move_executor import MoveExecutor
from core.preview_builder import PreviewBuilder
from core.scanner import DesktopScanner
from core.task_store import TaskStore
from models.desktop import DesktopItem, PreviewItem
from utils.paths import RuntimePaths


class DesktopService:
    """Coordinate desktop scan, preview, and execution workflows."""

    def __init__(self, runtime_paths: RuntimePaths) -> None:
        self.scanner = DesktopScanner()
        self.classifier = DesktopClassifier()
        self.preview_builder = PreviewBuilder()
        self.task_store = TaskStore(runtime_paths)
        self.move_executor = MoveExecutor(self.task_store)

    def scan_desktop(self, desktop_root: Path, config: AppConfig) -> list[DesktopItem]:
        """Scan the top-level desktop entries according to config rules."""
        return self.scanner.scan(
            desktop_root,
            whitelist_names=set(config.general.whitelist_names),
            whitelist_extensions=set(config.general.whitelist_extensions),
            skip_hidden=config.general.skip_hidden_files,
            skip_system=config.general.skip_system_files,
        )

    def build_preview(
        self,
        scanned_items: list[DesktopItem],
        desktop_root: Path,
        config: AppConfig,
    ) -> list[PreviewItem]:
        """Build preview rows for scanned desktop items."""
        preview_items: list[PreviewItem] = []
        for item in scanned_items:
            classification = self.classifier.classify(
                item,
                low_confidence_threshold=config.general.low_confidence_threshold,
                enable_paper_subcategory=config.general.enable_paper_subcategory,
            )
            preview_items.append(
                self.preview_builder.build(
                    item=item,
                    classification=classification,
                    desktop_root=desktop_root,
                    archive_root_name=config.general.archive_root_name,
                    move_folders=config.general.move_folders,
                )
            )
        return preview_items

    def execute_preview(self, preview_items: list[PreviewItem]):
        """Execute a desktop preview task."""
        return self.move_executor.execute("desktop_organize", preview_items)
