"""Preview construction for desktop organization."""

from __future__ import annotations

from pathlib import Path

from classifiers.base import ClassificationResult
from models.desktop import DesktopItem, PreviewItem


class PreviewBuilder:
    """Build preview rows from scanned items and classification results."""

    def build(
        self,
        item: DesktopItem,
        classification: ClassificationResult,
        desktop_root: Path,
        archive_root_name: str,
        move_folders: bool,
    ) -> PreviewItem:
        """Build a preview row for a single scanned item."""
        if item.is_skipped:
            return PreviewItem(
                name=item.name,
                source_path=item.path,
                file_type=item.item_type,
                suggested_category=classification.category,
                target_path="",
                confidence=classification.confidence,
                reason=classification.reason,
                is_skipped=True,
                skip_reason=item.skip_reason,
                subcategory=classification.subcategory,
            )

        if item.item_type == "folder" and not move_folders:
            return PreviewItem(
                name=item.name,
                source_path=item.path,
                file_type=item.item_type,
                suggested_category=classification.category,
                target_path="",
                confidence=classification.confidence,
                reason=classification.reason,
                is_skipped=True,
                skip_reason="folder_move_disabled",
                subcategory=classification.subcategory,
            )

        if classification.category == "发票候选":
            return PreviewItem(
                name=item.name,
                source_path=item.path,
                file_type=item.item_type,
                suggested_category=classification.category,
                target_path="",
                confidence=classification.confidence,
                reason=classification.reason,
                is_skipped=True,
                skip_reason="invoice_candidate",
                subcategory=classification.subcategory,
            )

        target_path = self._build_target_path(
            name=item.name,
            desktop_root=desktop_root,
            archive_root_name=archive_root_name,
            category=classification.category,
            subcategory=classification.subcategory,
        )
        return PreviewItem(
            name=item.name,
            source_path=item.path,
            file_type=item.item_type,
            suggested_category=classification.category,
            target_path=str(target_path),
            confidence=classification.confidence,
            reason=classification.reason,
            is_skipped=False,
            skip_reason="",
            subcategory=classification.subcategory,
        )

    def _build_target_path(
        self,
        name: str,
        desktop_root: Path,
        archive_root_name: str,
        category: str,
        subcategory: str,
    ) -> Path:
        """Build the target archive path for a classified item."""
        target_dir = desktop_root / archive_root_name / category
        if category == "文献" and subcategory:
            target_dir = target_dir / subcategory
        return target_dir / name
